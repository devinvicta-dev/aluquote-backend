"""
AluQuote AI - PDF Reader Module (The "Document Analyst") - ENHANCED VERSION
Leitura exaustiva de PDFs para extração de especificações técnicas
Correlação com dados DXF - PDF serve como fonte de especificações quando há DXF
"""

import pdfplumber
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import re
from pathlib import Path
from collections import defaultdict
import subprocess
import tempfile
import os

# OCR imports - Using PyMuPDF instead of Poppler for better Windows compatibility
OCR_AVAILABLE = False
PYMUPDF_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    import pytesseract
    from PIL import Image
    import io
    
    # Configurar caminho do Tesseract no Windows
    import platform
    if platform.system() == 'Windows':
        tesseract_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe',
        ]
        for path in tesseract_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break
    
    OCR_AVAILABLE = True
    PYMUPDF_AVAILABLE = True
    print("OCR disponível: PyMuPDF + pytesseract")
except ImportError as e:
    print(f"OCR não disponível. Instale: pip install pymupdf pytesseract pillow")
    print(f"  Erro: {e}")

# Fallback to pdf2image if PyMuPDF not available
if not PYMUPDF_AVAILABLE:
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
        OCR_AVAILABLE = True
        print("OCR disponível: pdf2image + pytesseract (requer Poppler)")
    except ImportError:
        pass


@dataclass
class BOMItem:
    """Bill of Materials line item"""
    row_id: int
    reference: str
    description: str
    quantity: float
    unit: str
    length_mm: Optional[float]
    width_mm: Optional[float]
    height_mm: Optional[float]
    thickness_mm: Optional[float]
    material: Optional[str]
    finish: Optional[str]
    notes: str
    confidence: float
    source_page: int
    raw_row: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_id": self.row_id,
            "reference": self.reference,
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit,
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "thickness_mm": self.thickness_mm,
            "material": self.material,
            "finish": self.finish,
            "notes": self.notes,
            "confidence": round(self.confidence, 2),
            "source_page": self.source_page
        }


@dataclass
class TechnicalConstraint:
    """Technical constraint extracted from prose text"""
    constraint_type: str
    value: str
    context: str
    source_page: int
    importance: str = "medium"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_type": self.constraint_type,
            "value": self.value,
            "context": self.context,
            "source_page": self.source_page,
            "importance": self.importance
        }


@dataclass
class ExtractedText:
    """Structured text extracted from PDF"""
    content: str
    page: int
    section: Optional[str]
    contains_quantities: bool
    contains_dimensions: bool
    contains_materials: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content,
            "page": self.page,
            "section": self.section,
            "contains_quantities": self.contains_quantities,
            "contains_dimensions": self.contains_dimensions,
            "contains_materials": self.contains_materials
        }


class PDFReader:
    """
    Advanced PDF Reader - The "Document Analyst" - ENHANCED VERSION
    Leitura EXAUSTIVA de todos os ficheiros PDF
    """
    
    # Header normalization mappings - EXTENDED
    HEADER_MAPPINGS = {
        # Quantity
        'qty': 'quantity', 'quant': 'quantity', 'quant.': 'quantity',
        'quantidade': 'quantity', 'qtd': 'quantity', 'qtd.': 'quantity',
        'un': 'quantity', 'units': 'quantity', 'pcs': 'quantity',
        'amount': 'quantity', 'count': 'quantity', 'qte': 'quantity',
        'no.': 'quantity', 'n.': 'quantity', 'numero': 'quantity',
        
        # Reference
        'ref': 'reference', 'ref.': 'reference', 'referência': 'reference',
        'code': 'reference', 'código': 'reference', 'item': 'reference',
        'part': 'reference', 'part no': 'reference', 'part no.': 'reference',
        'profile': 'reference', 'perfil': 'reference', 'cod': 'reference',
        'cod.': 'reference', 'artigo': 'reference', 'art': 'reference',
        'pos': 'reference', 'pos.': 'reference', 'position': 'reference',
        
        # Description
        'desc': 'description', 'desc.': 'description', 'descrição': 'description',
        'name': 'description', 'nome': 'description', 'designação': 'description',
        'designation': 'description', 'item description': 'description',
        'descricao': 'description', 'produto': 'description', 'product': 'description',
        'componente': 'description', 'component': 'description',
        
        # Length
        'length': 'length', 'len': 'length', 'l': 'length',
        'comprimento': 'length', 'comp': 'length', 'comp.': 'length',
        'lgth': 'length', 'long': 'length', 'c': 'length',
        
        # Width
        'width': 'width', 'w': 'width', 'largura': 'width',
        'larg': 'width', 'larg.': 'width', 'l.': 'width',
        
        # Height
        'height': 'height', 'h': 'height', 'altura': 'height',
        'alt': 'height', 'alt.': 'height',
        
        # Thickness
        'thickness': 'thickness', 'esp': 'thickness', 'espessura': 'thickness',
        'th': 'thickness', 'thk': 'thickness', 'e': 'thickness',
        
        # Material
        'material': 'material', 'mat': 'material', 'mat.': 'material',
        'alloy': 'material', 'liga': 'material', 'tipo': 'material',
        
        # Finish/Treatment
        'finish': 'finish', 'acabamento': 'finish', 'acabam': 'finish',
        'treatment': 'finish', 'tratamento': 'finish', 'trat': 'finish',
        'coating': 'finish', 'revestimento': 'finish', 'cor': 'finish',
        'color': 'finish', 'colour': 'finish',
        
        # Unit
        'unit': 'unit', 'un.': 'unit', 'unidade': 'unit',
        'uom': 'unit', 'u/m': 'unit', 'unid': 'unit',
        
        # Weight
        'weight': 'weight', 'peso': 'weight', 'kg': 'weight',
        'mass': 'weight', 'massa': 'weight',
        
        # Price
        'price': 'price', 'preço': 'price', 'preco': 'price',
        'valor': 'price', 'cost': 'price', 'custo': 'price',
        '€': 'price', 'eur': 'price',
        
        # Notes
        'notes': 'notes', 'obs': 'notes', 'obs.': 'notes',
        'observações': 'notes', 'remarks': 'notes', 'notas': 'notes',
        'comments': 'notes', 'comentários': 'notes',
    }
    
    # Technical constraint patterns - EXTENDED
    CONSTRAINT_PATTERNS = {
        'surface_treatment': [
            r'(qualicoat|qualideco|qualanod)',
            r'(anodizado|anodized|anodização|anodising)',
            r'(lacado|lacquered|powder[\s\-]?coat)',
            r'(seaside|marine|marítimo|maritimo)',
            r'(classe\s*\d+|class\s*\d+)',
            r'(ral\s*\d{4})',
            r'(pintura|painting|painted)',
            r'(termolacado|thermolacquered)',
        ],
        'material_grade': [
            r'(EN\s*AW[\s\-]?\d{4})',
            r'(6060|6063|6005|6082)[\s\-]?(T\d+)?',
            r'(T5|T6|T66)',
            r'(alumínio|aluminum|aluminium)',
            r'(liga\s+\d{4})',
            r'(alloy\s+\d{4})',
            r'(inox|stainless)',
        ],
        'tolerance': [
            r'(tolerância|tolerance)[:\s]*([\d.,±]+\s*mm)',
            r'(±\s*[\d.,]+\s*mm)',
            r'(\+/?-\s*[\d.,]+)',
        ],
        'certification': [
            r'(CE\s*marking|marcação\s*CE)',
            r'(ISO\s*\d{4,5})',
            r'(EN\s*\d{4,5})',
            r'(NP\s*\d{3,4})',
            r'(DIN\s*\d{4,5})',
        ],
        'thermal_performance': [
            r'(Uf?\s*[=<>]\s*[\d.,]+)',
            r'(thermal\s*break|corte\s*térmico)',
            r'(RPT|poliamida)',
            r'(W/m[²2]K)',
        ],
        'acoustic_performance': [
            r'(Rw\s*[=<>]\s*\d+)',
            r'(dB|decibel)',
            r'(acoustic|acústic)',
        ],
        'fire_rating': [
            r'(EI\s*\d+|E\s*\d+)',
            r'(fire\s*rat|resist[êe]ncia\s*fogo)',
            r'(class[ie]\s*[A-F]\d?)',
        ],
        'water_tightness': [
            r'(class[ie]\s*\d+[A-E]?)',
            r'(estanque|watertight)',
            r'(Pa|pascal)',
        ],
        'dimension_spec': [
            r'(\d+(?:[.,]\d+)?\s*[xX×]\s*\d+(?:[.,]\d+)?(?:\s*[xX×]\s*\d+(?:[.,]\d+)?)?)',
            r'(espessura|thickness)[:\s]*(\d+(?:[.,]\d+)?)',
            r'(largura|width)[:\s]*(\d+(?:[.,]\d+)?)',
            r'(altura|height)[:\s]*(\d+(?:[.,]\d+)?)',
        ],
        'glass_spec': [
            r'(\d+[+/]\d+[+/]\d+)',  # Glass composition like 6/16/6
            r'(vidro|glass|cristal)',
            r'(duplo|double|triplo|triple)',
            r'(temperado|tempered|laminado|laminated)',
            r'(low[\-\s]?e|baixa\s*emissividade)',
        ],
        'hardware': [
            r'(dobradiça|hinge)',
            r'(puxador|handle)',
            r'(fechadura|lock)',
            r'(ferragem|hardware)',
            r'(acessório|accessory)',
        ],
        'seal_gasket': [
            r'(vedante|seal|gasket)',
            r'(epdm|silicone)',
            r'(borracha|rubber)',
            r'(junta|joint)',
        ],
    }
    
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.bom_items: List[BOMItem] = []
        self.constraints: List[TechnicalConstraint] = []
        self.extracted_texts: List[ExtractedText] = []
        self.raw_tables: List[Dict] = []
        self.document_info: Dict[str, Any] = {}
        self.all_text_content: List[Dict] = []
        self.dimension_specs: List[Dict] = []
        self.material_specs: List[Dict] = []
        self.is_scanned_pdf = False
        self.ocr_text_content: List[Dict] = []
        
    def parse(self) -> Dict[str, Any]:
        """Main parsing method - EXHAUSTIVE analysis of all pages with OCR fallback"""
        try:
            total_text_extracted = 0
            total_pages = 0
            
            with pdfplumber.open(str(self.file_path)) as pdf:
                total_pages = len(pdf.pages)
                self.document_info = {
                    "filename": self.file_path.name,
                    "total_pages": total_pages,
                    "metadata": pdf.metadata or {}
                }
                
                # First pass: try standard text extraction
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    total_text_extracted += len(text.strip())
                    self._process_page_exhaustive(page, page_num)
            
            # Check if PDF is scanned or has fragmented text (CAD drawings)
            avg_text_per_page = total_text_extracted / max(total_pages, 1)
            is_fragmented = self._check_if_text_fragmented()
            
            needs_ocr = (avg_text_per_page < 100) or is_fragmented
            
            if needs_ocr:
                reason = "texto fragmentado" if is_fragmented else f"{avg_text_per_page:.0f} chars/página"
                self.is_scanned_pdf = True
                self.document_info["is_scanned"] = True
                self.document_info["is_technical_drawing"] = is_fragmented
                self.document_info["ocr_applied"] = False
                
                # Try OCR if available
                if OCR_AVAILABLE:
                    print(f"PDF com {reason} detectado. Aplicando OCR...")
                    self._apply_ocr_to_pdf()
                    self.document_info["ocr_applied"] = True
                else:
                    print(f"PDF com {reason} detectado mas OCR não está disponível.")
            
            # Post-processing
            self._validate_and_dedupe_bom_items()
            self._extract_additional_specs()
            self._correlate_constraints_with_items()
            
            return {
                "success": True,
                "document_info": self.document_info,
                "bom_items": [item.to_dict() for item in self.bom_items],
                "constraints": [c.to_dict() for c in self.constraints],
                "extracted_texts": [t.to_dict() for t in self.extracted_texts[:50]],
                "raw_tables_count": len(self.raw_tables),
                "dimension_specs": self.dimension_specs,
                "material_specs": self.material_specs,
                "ocr_content": self.ocr_text_content[:10] if self.ocr_text_content else [],
                "statistics": {
                    "total_items": len(self.bom_items),
                    "total_quantity": sum(item.quantity for item in self.bom_items),
                    "unique_references": len(set(item.reference for item in self.bom_items if item.reference)),
                    "total_constraints": len(self.constraints),
                    "pages_with_tables": len(set(t['page'] for t in self.raw_tables)),
                    "total_text_blocks": len(self.all_text_content),
                    "ocr_pages_processed": len(self.ocr_text_content),
                    "is_scanned_pdf": self.is_scanned_pdf
                },
                "profile_references": self._extract_all_profile_references(),
                "summary": self._generate_detailed_summary()
            }
                
        except Exception as e:
            import traceback
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "document_info": {"filename": self.file_path.name}
            }
    
    def _process_page_exhaustive(self, page, page_num: int):
        """Process a single PDF page EXHAUSTIVELY"""
        
        # 1. Extract ALL tables on this page
        tables = page.extract_tables()
        for table in tables:
            if table and len(table) > 0:
                self._parse_table_exhaustive(table, page_num)
        
        # 2. Also try table extraction with different settings
        try:
            tables_v2 = page.extract_tables(table_settings={
                "vertical_strategy": "text",
                "horizontal_strategy": "text"
            })
            for table in tables_v2:
                if table and len(table) > 0:
                    # Check if this table adds new data
                    self._parse_table_exhaustive(table, page_num)
        except:
            pass
        
        # 3. Extract ALL text content
        text = page.extract_text() or ""
        if text.strip():
            # Store full text
            self.all_text_content.append({
                "page": page_num,
                "content": text
            })
            
            # Extract constraints from text
            self._extract_constraints_exhaustive(text, page_num)
            
            # Extract structured text blocks
            self._extract_text_blocks(text, page_num)
            
            # Try to extract items from unstructured text
            self._extract_items_from_text(text, page_num)
        
        # 4. Extract words with positions for spatial analysis
        try:
            words = page.extract_words()
            self._analyze_word_positions(words, page_num)
        except:
            pass
    
    def _parse_table_exhaustive(self, table: List[List[str]], page_num: int):
        """Parse a table exhaustively, trying multiple interpretation strategies"""
        if not table or len(table) < 1:
            return
        
        # Store raw table
        self.raw_tables.append({
            "page": page_num,
            "rows": len(table),
            "cols": len(table[0]) if table[0] else 0,
            "sample": table[:3] if len(table) >= 3 else table
        })
        
        # Strategy 1: First row as headers
        if len(table) >= 2:
            headers = self._normalize_headers(table[0])
            if self._is_valid_header_row(headers):
                self._extract_bom_from_table(table[1:], headers, page_num)
        
        # Strategy 2: Try without headers (detect from content)
        self._try_headerless_extraction(table, page_num)
        
        # Strategy 3: Look for key-value pairs
        self._extract_key_value_pairs(table, page_num)
    
    def _normalize_headers(self, header_row: List[str]) -> Dict[int, str]:
        """Normalize table headers"""
        normalized = {}
        
        for idx, header in enumerate(header_row):
            if not header:
                continue
            
            header_clean = str(header).lower().strip()
            header_clean = re.sub(r'\s+', ' ', header_clean)
            
            # Direct mapping
            if header_clean in self.HEADER_MAPPINGS:
                normalized[idx] = self.HEADER_MAPPINGS[header_clean]
            else:
                # Partial match
                for pattern, standard in self.HEADER_MAPPINGS.items():
                    if pattern in header_clean or header_clean in pattern:
                        normalized[idx] = standard
                        break
                else:
                    normalized[idx] = header_clean
        
        return normalized
    
    def _is_valid_header_row(self, headers: Dict[int, str]) -> bool:
        """Check if headers suggest a valid BOM table"""
        important_fields = {'quantity', 'reference', 'description', 'length', 'material'}
        return len(set(headers.values()) & important_fields) >= 1
    
    def _extract_bom_from_table(self, rows: List[List[str]], headers: Dict[int, str], page_num: int):
        """Extract BOM items from table rows"""
        for row in rows:
            if not row or all(not cell for cell in row):
                continue
            
            item = self._parse_row_to_item(row, headers, page_num)
            if item:
                self.bom_items.append(item)
    
    def _parse_row_to_item(self, row: List[str], headers: Dict[int, str], page_num: int) -> Optional[BOMItem]:
        """Parse a single row into a BOMItem"""
        try:
            data = {}
            confidence_scores = []
            
            for idx, cell in enumerate(row):
                if idx in headers:
                    field = headers[idx]
                    value, conf = self._parse_cell_value(cell, field)
                    data[field] = value
                    confidence_scores.append(conf)
            
            # Must have at least some identifying info
            if not data.get('reference') and not data.get('description'):
                # Try to use first non-empty cell as description
                for cell in row:
                    if cell and cell.strip():
                        data['description'] = cell.strip()
                        break
            
            if not data.get('reference') and not data.get('description'):
                return None
            
            quantity = self._extract_number(data.get('quantity', '1'))
            if quantity is None or quantity <= 0:
                quantity = 1
            
            return BOMItem(
                row_id=len(self.bom_items) + 1,
                reference=str(data.get('reference', '')).strip(),
                description=str(data.get('description', '')).strip(),
                quantity=quantity,
                unit=str(data.get('unit', 'un')).strip() or 'un',
                length_mm=self._extract_number(data.get('length')),
                width_mm=self._extract_number(data.get('width')),
                height_mm=self._extract_number(data.get('height')),
                thickness_mm=self._extract_number(data.get('thickness')),
                material=data.get('material'),
                finish=data.get('finish'),
                notes=str(data.get('notes', '')).strip(),
                confidence=sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.5,
                source_page=page_num,
                raw_row=row
            )
            
        except:
            return None
    
    def _parse_cell_value(self, cell: str, field_type: str) -> Tuple[Any, float]:
        """Parse a cell value with confidence score"""
        if not cell:
            return None, 0.0
        
        cell_str = str(cell).strip()
        confidence = 1.0
        
        # Check for OCR issues
        if re.search(r'[^\x00-\x7F€£¥°±²³µ¶·¹ºÀ-ÿ\s]', cell_str):
            confidence -= 0.2
        
        # Numeric fields
        if field_type in ('quantity', 'length', 'width', 'height', 'thickness', 'weight', 'price'):
            num = self._extract_number(cell_str)
            if num is None:
                confidence -= 0.3
            return num, max(0, confidence)
        
        return cell_str, confidence
    
    def _extract_number(self, value: Any) -> Optional[float]:
        """Extract numeric value"""
        if value is None:
            return None
        
        value_str = str(value).strip()
        if not value_str:
            return None
        
        # Remove units
        value_str = re.sub(r'(mm|cm|m|kg|un|pcs?|€|eur)', '', value_str, flags=re.IGNORECASE)
        value_str = value_str.strip()
        
        # European format
        if ',' in value_str and '.' not in value_str:
            value_str = value_str.replace(',', '.')
        elif ',' in value_str and '.' in value_str:
            value_str = value_str.replace(',', '')
        
        match = re.search(r'[\d.]+', value_str)
        if match:
            try:
                return float(match.group())
            except:
                return None
        return None
    
    def _try_headerless_extraction(self, table: List[List[str]], page_num: int):
        """Try to extract data from tables without clear headers"""
        for row in table:
            if not row or len(row) < 2:
                continue
            
            # Look for patterns that suggest a BOM row
            has_number = False
            has_text = False
            
            for cell in row:
                if cell:
                    cell_str = str(cell).strip()
                    if re.match(r'^\d+([.,]\d+)?$', cell_str):
                        has_number = True
                    elif len(cell_str) > 3:
                        has_text = True
            
            if has_number and has_text:
                # Try to interpret as: ref, description, qty, dimensions...
                item = self._interpret_row_heuristically(row, page_num)
                if item:
                    self.bom_items.append(item)
    
    def _interpret_row_heuristically(self, row: List[str], page_num: int) -> Optional[BOMItem]:
        """Interpret a row without known headers"""
        try:
            reference = ""
            description = ""
            quantity = 1
            length = None
            
            for i, cell in enumerate(row):
                if not cell:
                    continue
                cell_str = str(cell).strip()
                
                # First short alphanumeric is likely reference
                if not reference and re.match(r'^[A-Z0-9\-_\.]{2,15}$', cell_str, re.IGNORECASE):
                    reference = cell_str
                # Longer text is description
                elif not description and len(cell_str) > 10 and not cell_str.replace(',', '').replace('.', '').isdigit():
                    description = cell_str
                # Numbers
                else:
                    num = self._extract_number(cell_str)
                    if num:
                        if num < 1000 and quantity == 1:
                            quantity = int(num) if num == int(num) else num
                        elif num > 10:
                            length = num
            
            if reference or description:
                return BOMItem(
                    row_id=len(self.bom_items) + 1,
                    reference=reference,
                    description=description,
                    quantity=quantity,
                    unit='un',
                    length_mm=length,
                    width_mm=None,
                    height_mm=None,
                    thickness_mm=None,
                    material=None,
                    finish=None,
                    notes="",
                    confidence=0.5,
                    source_page=page_num,
                    raw_row=row
                )
        except:
            pass
        return None
    
    def _extract_key_value_pairs(self, table: List[List[str]], page_num: int):
        """Extract key-value pairs from 2-column tables"""
        if not table:
            return
        
        for row in table:
            if len(row) >= 2:
                key = str(row[0]).strip().lower() if row[0] else ""
                value = str(row[1]).strip() if row[1] else ""
                
                if key and value:
                    # Check if it's a dimension spec
                    if any(k in key for k in ['comprimento', 'length', 'largura', 'width', 'altura', 'height', 'espessura', 'thickness']):
                        self.dimension_specs.append({
                            "key": key,
                            "value": value,
                            "page": page_num
                        })
                    # Material spec
                    elif any(k in key for k in ['material', 'liga', 'alloy', 'acabamento', 'finish']):
                        self.material_specs.append({
                            "key": key,
                            "value": value,
                            "page": page_num
                        })
    
    def _extract_constraints_exhaustive(self, text: str, page_num: int):
        """Extract ALL technical constraints from text"""
        text_lower = text.lower()
        
        for constraint_type, patterns in self.CONSTRAINT_PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(text), match.end() + 100)
                    context = text[start:end].strip()
                    context = re.sub(r'\s+', ' ', context)
                    
                    # Determine importance
                    importance = "medium"
                    if constraint_type in ['surface_treatment', 'material_grade', 'certification']:
                        importance = "high"
                    elif constraint_type in ['hardware', 'seal_gasket']:
                        importance = "low"
                    
                    self.constraints.append(TechnicalConstraint(
                        constraint_type=constraint_type,
                        value=match.group(),
                        context=context,
                        source_page=page_num,
                        importance=importance
                    ))
    
    def _extract_text_blocks(self, text: str, page_num: int):
        """Extract structured text blocks"""
        # Split by double newlines or section indicators
        blocks = re.split(r'\n\s*\n|\n(?=[A-Z0-9]{1,3}[\.\)]\s)', text)
        
        for block in blocks:
            block = block.strip()
            if len(block) < 10:
                continue
            
            # Analyze block content
            contains_qty = bool(re.search(r'\b\d+\s*(un|pcs|x|peças?)\b', block, re.IGNORECASE))
            contains_dim = bool(re.search(r'\d+\s*[xX×]\s*\d+|\d+\s*mm', block))
            contains_mat = bool(re.search(r'alumínio|aluminum|vidro|glass|aço|steel', block, re.IGNORECASE))
            
            # Detect section
            section = None
            if re.match(r'^[A-Z\s]{5,}$', block.split('\n')[0]):
                section = block.split('\n')[0].strip()
            
            self.extracted_texts.append(ExtractedText(
                content=block,
                page=page_num,
                section=section,
                contains_quantities=contains_qty,
                contains_dimensions=contains_dim,
                contains_materials=contains_mat
            ))
    
    def _extract_items_from_text(self, text: str, page_num: int):
        """Extract BOM items from unstructured text"""
        # Pattern: quantity followed by description
        patterns = [
            r'(\d+)\s*(?:x|un\.?|pcs?\.?|peças?)\s+(.{10,60})',
            r'(\d+)\s+(.{10,60}?)\s+(?:\d+\s*mm)',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    qty = int(match.group(1))
                    desc = match.group(2).strip()
                    
                    if qty > 0 and qty < 1000 and len(desc) > 5:
                        # Check if not already extracted
                        if not any(desc.lower() in item.description.lower() for item in self.bom_items):
                            self.bom_items.append(BOMItem(
                                row_id=len(self.bom_items) + 1,
                                reference="",
                                description=desc,
                                quantity=qty,
                                unit='un',
                                length_mm=None,
                                width_mm=None,
                                height_mm=None,
                                thickness_mm=None,
                                material=None,
                                finish=None,
                                notes=f"Extracted from text, page {page_num}",
                                confidence=0.4,
                                source_page=page_num
                            ))
                except:
                    continue
    
    def _analyze_word_positions(self, words: List[Dict], page_num: int):
        """Analyze word positions for additional extraction"""
        # Group words by approximate Y position (rows)
        rows = defaultdict(list)
        for word in words:
            y_key = round(word.get('top', 0) / 10) * 10
            rows[y_key].append(word)
        
        # Sort rows by position
        for y_key in sorted(rows.keys()):
            row_words = sorted(rows[y_key], key=lambda w: w.get('x0', 0))
            row_text = ' '.join(w.get('text', '') for w in row_words)
            
            # Look for dimension patterns
            dim_match = re.search(r'(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)', row_text)
            if dim_match:
                self.dimension_specs.append({
                    "dimensions": f"{dim_match.group(1)} x {dim_match.group(2)}",
                    "context": row_text[:100],
                    "page": page_num
                })
    
    def _validate_and_dedupe_bom_items(self):
        """Validate and remove duplicate/invalid BOM items"""
        seen = set()
        valid_items = []
        
        for item in self.bom_items:
            # Filter out invalid items
            if not self._is_valid_bom_item(item):
                continue
            
            # Create dedup key
            key = (
                item.reference.lower() if item.reference else "",
                item.description.lower()[:50] if item.description else "",
                item.quantity,
                item.source_page
            )
            
            if key not in seen:
                seen.add(key)
                valid_items.append(item)
        
        # Re-number
        for idx, item in enumerate(valid_items, 1):
            item.row_id = idx
        
        self.bom_items = valid_items
    
    def _is_valid_bom_item(self, item: BOMItem) -> bool:
        """Check if a BOM item is valid (not garbage from CAD text)"""
        ref = item.reference or ""
        desc = item.description or ""
        
        # Combine for analysis
        combined = f"{ref} {desc}".strip()
        
        # Too short or empty
        if len(combined) < 4:
            return False
        
        # Check for fragmented text (common in CAD drawings)
        newline_ratio = combined.count('\n') / max(len(combined), 1)
        if newline_ratio > 0.1:
            return False
        
        # Check for vertical text patterns (single chars per line)
        lines = combined.split('\n')
        single_char_lines = sum(1 for l in lines if len(l.strip()) <= 2)
        if len(lines) > 2 and single_char_lines / len(lines) > 0.4:
            return False
        
        # Must have at least one word with 3+ consecutive letters
        if not re.search(r'[a-zA-ZÀ-ÿ]{3,}', combined):
            return False
        
        # Clean text for analysis
        combined_clean = re.sub(r'[\s\n]+', ' ', combined).strip().lower()
        
        # Must be at least 5 chars after cleaning
        if len(combined_clean) < 5:
            return False
        
        # Filter out common CAD metadata
        invalid_patterns = [
            r'^(aprovado|data|rev\.?|escala|folha|desenho|cliente|projeto|kg|mm|un)[\s\.]*$',
            r'^\d{2}[\./]\d{2}[\./]\d{2,4}$',  # Dates
            r'^[A-Z]{1,3}[\s\.]*$',  # Single letters
            r'^\d+[\.,]?\d*$',  # Pure numbers
            r'^[a-z]\s*[a-z]\s*[a-z]',  # Spaced single letters
        ]
        for pattern in invalid_patterns:
            if re.match(pattern, combined_clean, re.IGNORECASE):
                return False
        
        # Check for spaced-out letters (OCR artifact)
        words = combined_clean.split()
        if all(len(w) <= 2 for w in words):
            return False
        
        # Check for too many numbers/symbols vs letters
        letters = len(re.findall(r'[a-zA-ZÀ-ÿ]', combined_clean))
        if letters < 4:
            return False
        
        # Reject if looks like garbled OCR (lots of mixed short segments)
        if len(words) > 5 and sum(1 for w in words if len(w) <= 2) / len(words) > 0.5:
            return False
        
        return True
    
    def _extract_additional_specs(self):
        """Extract additional specifications from all content"""
        all_text = ' '.join(t['content'] for t in self.all_text_content)
        
        # Extract standard dimension formats
        dim_patterns = [
            r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)',  # L x W x H
            r'(\d+)\s*[xX×]\s*(\d+)',  # L x W
        ]
        
        for pattern in dim_patterns:
            for match in re.finditer(pattern, all_text):
                self.dimension_specs.append({
                    "raw": match.group(),
                    "type": "extracted"
                })
    
    def _correlate_constraints_with_items(self):
        """Correlate constraints with BOM items"""
        # Add material/finish info to items if found on same page
        for item in self.bom_items:
            page = item.source_page
            page_constraints = [c for c in self.constraints if c.source_page == page]
            
            for constraint in page_constraints:
                if constraint.constraint_type == 'material_grade' and not item.material:
                    item.material = constraint.value
                elif constraint.constraint_type == 'surface_treatment' and not item.finish:
                    item.finish = constraint.value
    
    def _extract_all_profile_references(self) -> List[str]:
        """Extract all unique profile references"""
        references = set()
        
        for item in self.bom_items:
            if item.reference:
                ref = item.reference.upper().strip()
                ref = re.sub(r'\s+', ' ', ref)
                references.add(ref)
        
        # Also from constraints
        for constraint in self.constraints:
            if constraint.constraint_type in ['material_grade', 'dimension_spec']:
                ref_match = re.search(r'[A-Z]{1,3}[\-_]?\d{2,4}', constraint.value, re.IGNORECASE)
                if ref_match:
                    references.add(ref_match.group().upper())
        
        return sorted(list(references))
    
    def _generate_detailed_summary(self) -> Dict[str, Any]:
        """Generate detailed document summary"""
        material_types = set()
        surface_treatments = set()
        certifications = set()
        
        for item in self.bom_items:
            if item.material:
                material_types.add(item.material)
            if item.finish:
                surface_treatments.add(item.finish)
        
        for constraint in self.constraints:
            if constraint.constraint_type == 'surface_treatment':
                surface_treatments.add(constraint.value)
            elif constraint.constraint_type == 'material_grade':
                material_types.add(constraint.value)
            elif constraint.constraint_type == 'certification':
                certifications.add(constraint.value)
        
        return {
            "unique_profiles": len(self._extract_all_profile_references()),
            "total_line_items": len(self.bom_items),
            "material_types": list(material_types),
            "surface_treatments": list(surface_treatments),
            "certifications": list(certifications),
            "pages_with_tables": len(set(t['page'] for t in self.raw_tables)),
            "total_constraints": len(self.constraints),
            "constraint_types": list(set(c.constraint_type for c in self.constraints)),
            "high_importance_constraints": len([c for c in self.constraints if c.importance == 'high']),
            "dimension_specs_found": len(self.dimension_specs),
            "confidence_distribution": {
                "high": len([i for i in self.bom_items if i.confidence >= 0.8]),
                "medium": len([i for i in self.bom_items if 0.5 <= i.confidence < 0.8]),
                "low": len([i for i in self.bom_items if i.confidence < 0.5])
            }
        }


    def _check_if_text_fragmented(self) -> bool:
        """Check if extracted text is fragmented (typical of CAD drawings)"""
        if not self.all_text_content:
            return False
        
        total_chars = 0
        total_newlines = 0
        single_char_lines = 0
        total_lines = 0
        
        for text_block in self.all_text_content:
            content = text_block.get('content', '')
            total_chars += len(content)
            total_newlines += content.count('\n')
            
            lines = content.split('\n')
            total_lines += len(lines)
            single_char_lines += sum(1 for l in lines if len(l.strip()) <= 1)
        
        if total_chars == 0 or total_lines == 0:
            return False
        
        # High newline ratio suggests fragmented text
        newline_ratio = total_newlines / max(total_chars, 1)
        
        # High single-char line ratio suggests vertical/scattered text
        single_char_ratio = single_char_lines / max(total_lines, 1)
        
        # Consider fragmented if either ratio is high
        return newline_ratio > 0.15 or single_char_ratio > 0.3
    
    def _apply_ocr_to_pdf(self):
        """Apply OCR to scanned PDF pages"""
        if not OCR_AVAILABLE:
            print("OCR ignorado: bibliotecas Python não instaladas")
            return
        
        # Convert PDF to images using PyMuPDF (no Poppler needed)
        images = []
        try:
            if PYMUPDF_AVAILABLE:
                # Use PyMuPDF (fitz) - works on Windows without Poppler
                pdf_doc = fitz.open(str(self.file_path))
                max_pages = min(len(pdf_doc), 5)  # Limit to 5 pages
                
                for page_num in range(max_pages):
                    page = pdf_doc[page_num]
                    # Render at 150 DPI (default is 72)
                    zoom = 150 / 72
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat)
                    
                    # Convert to PIL Image
                    img_data = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_data))
                    images.append(img)
                
                pdf_doc.close()
                print(f"OCR: Convertidas {len(images)} páginas com PyMuPDF")
            else:
                # Fallback to pdf2image (requires Poppler)
                from pdf2image import convert_from_path
                images = convert_from_path(str(self.file_path), dpi=150)[:5]
                print(f"OCR: Convertidas {len(images)} páginas com pdf2image")
                
        except Exception as e:
            print(f"OCR erro ao converter PDF: {str(e)}")
            self.document_info["ocr_skipped"] = True
            self.document_info["ocr_skip_reason"] = f"PDF conversion error: {str(e)}"
            return
        
        if not images:
            print("OCR: Nenhuma imagem extraída do PDF")
            return
        
        try:
            
            # Limit OCR to first 5 pages for performance
            max_ocr_pages = min(len(images), 5)
            for page_num, image in enumerate(images[:max_ocr_pages], 1):
                try:
                    # Apply OCR with Portuguese + English
                    ocr_text = pytesseract.image_to_string(
                        image, 
                        lang='por+eng',
                        config='--psm 6'  # Assume uniform text block
                    )
                    
                    if ocr_text.strip():
                        self.ocr_text_content.append({
                            "page": page_num,
                            "content": ocr_text,
                            "source": "ocr"
                        })
                        
                        # Also store in all_text_content
                        self.all_text_content.append({
                            "page": page_num,
                            "content": ocr_text,
                            "source": "ocr"
                        })
                        
                        # Process the OCR text for constraints and items
                        self._extract_constraints_exhaustive(ocr_text, page_num)
                        self._extract_text_blocks(ocr_text, page_num)
                        self._extract_items_from_text(ocr_text, page_num)
                        
                        # Try to find tables in OCR text
                        self._extract_tables_from_ocr_text(ocr_text, page_num)
                        
                except Exception as e:
                    print(f"Erro OCR na página {page_num}: {e}")
                    continue
                    
        except Exception as e:
            print(f"Erro ao processar páginas OCR: {e}")
            self.document_info["ocr_error"] = str(e)
    
    def _extract_tables_from_ocr_text(self, text: str, page_num: int):
        """Try to extract table-like data from OCR text"""
        lines = text.strip().split('\n')
        
        # Look for lines that look like table rows
        potential_rows = []
        for line in lines:
            # Skip empty or very short lines
            if len(line.strip()) < 5:
                continue
            
            # Check if line has multiple "columns" (separated by multiple spaces or tabs)
            parts = re.split(r'\s{2,}|\t', line.strip())
            if len(parts) >= 2:
                # Clean parts
                parts = [p.strip() for p in parts if p.strip()]
                if len(parts) >= 2:
                    potential_rows.append(parts)
        
        # If we found potential table rows, try to parse them
        if len(potential_rows) >= 2:
            # Check if first row looks like headers
            first_row_lower = [str(p).lower() for p in potential_rows[0]]
            is_header = any(h in ' '.join(first_row_lower) for h in 
                          ['ref', 'desc', 'qty', 'quant', 'material', 'perfil', 'medida', 'un'])
            
            if is_header:
                headers = self._normalize_headers(potential_rows[0])
                for row in potential_rows[1:]:
                    item = self._parse_row_to_item(row, headers, page_num)
                    if item:
                        item.notes = f"OCR extracted, page {page_num}"
                        item.confidence *= 0.7  # Lower confidence for OCR
                        self.bom_items.append(item)
            else:
                # Try headerless extraction
                for row in potential_rows:
                    item = self._interpret_row_heuristically(row, page_num)
                    if item:
                        item.notes = f"OCR extracted (no headers), page {page_num}"
                        item.confidence *= 0.6
                        self.bom_items.append(item)
    
    def _extract_dimensions_from_drawing(self, text: str, page_num: int):
        """Extract dimension annotations from technical drawing OCR text"""
        # Patterns for dimension annotations commonly found in drawings
        dimension_patterns = [
            r'(\d{2,5})\s*(?:mm)?',  # Simple measurements
            r'(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)',  # L x W format
            r'[ØφΦ∅]\s*(\d+(?:[.,]\d+)?)',  # Diameter
            r'R\s*=?\s*(\d+(?:[.,]\d+)?)',  # Radius
            r'(\d+(?:[.,]\d+)?)\s*°',  # Angles
        ]
        
        for pattern in dimension_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                self.dimension_specs.append({
                    "raw": match.group(),
                    "page": page_num,
                    "source": "ocr_drawing",
                    "type": "dimension"
                })


def parse_pdf_file(file_path: str) -> Dict[str, Any]:
    """Convenience function to parse a PDF file"""
    reader = PDFReader(file_path)
    return reader.parse()
