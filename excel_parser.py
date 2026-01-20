"""
AluQuote AI - Excel Parser for FLYSTEEL/Tekla Cost Structure - V2 ENHANCED
Reads FLYSTEEL Excel cost structure files and Tekla XLS material lists.
Supports detection of duplicates, OMEGA profiles, and QTD × Peso calculation.

PRIORITY LOGIC:
1. Excel/XLS files are PRIMARY source for quantities (95%+ accuracy)
2. PDF files used for comparison and validation
3. CAD files used for complexity analysis (holes, welds)
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path
from io import StringIO

# Try to import openpyxl for .xlsx files
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# Try to import pandas for HTML-Excel files
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


@dataclass
class ProfileQuantity:
    """Steel profile quantity data"""
    reference: str
    designation: str
    length_ml: float
    weight_per_meter: float  # kg/m
    area_per_meter: float  # m2/m
    total_quantity_kg: float
    unit: str
    category: str  # 'estrutura', 'madres_cobertura', 'madres_fachada', 'omega', 'outros'
    material: str = ""  # S275JR, S355, etc.
    quantity_pcs: int = 1  # Number of pieces
    weight_per_piece: float = 0.0  # Weight per individual piece
    source_file: str = ""  # Source file name
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference,
            "designation": self.designation,
            "length_ml": round(self.length_ml, 2),
            "weight_per_meter": self.weight_per_meter,
            "area_per_meter": self.area_per_meter,
            "total_quantity_kg": round(self.total_quantity_kg, 2),
            "unit": self.unit,
            "category": self.category,
            "material": self.material,
            "quantity_pcs": self.quantity_pcs,
            "weight_per_piece": round(self.weight_per_piece, 2),
            "source_file": self.source_file
        }


@dataclass
class RevestimentoItem:
    """Cladding/Roofing item data (Revestimentos)"""
    reference: str
    designation: str
    quantity: float
    unit: str  # 'm2', 'ml', 'un'
    category: str  # 'cobertura', 'fachada'
    kg_per_ml: float = 0.0
    m2_per_ml: float = 0.0
    source_file: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference,
            "designation": self.designation,
            "quantity": round(self.quantity, 2),
            "unit": self.unit,
            "category": self.category,
            "kg_per_ml": self.kg_per_ml,
            "m2_per_ml": self.m2_per_ml,
            "source_file": self.source_file
        }


@dataclass
class SanityCheckResult:
    """Result of sanity check comparing calculated sum vs presented totals"""
    passed: bool
    column_name: str  # e.g., "Quantidade"
    calculated_sum: float
    presented_total: float  # Total shown in file (if any)
    difference: float
    difference_pct: float
    used_value: float  # Always the calculated sum (priority)
    warning_message: str
    items_checked: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "column_name": self.column_name,
            "calculated_sum": round(self.calculated_sum, 2),
            "presented_total": round(self.presented_total, 2) if self.presented_total else None,
            "difference": round(self.difference, 2),
            "difference_pct": round(self.difference_pct, 2),
            "used_value": round(self.used_value, 2),
            "warning_message": self.warning_message,
            "items_checked": self.items_checked
        }


@dataclass
class DuplicateWarning:
    """Warning about duplicate data between files"""
    profile_type: str
    file1: str
    file2: str
    value1: float
    value2: float
    difference_pct: float
    recommendation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_type": self.profile_type,
            "file1": self.file1,
            "file2": self.file2,
            "value1": round(self.value1, 2),
            "value2": round(self.value2, 2),
            "difference_pct": round(self.difference_pct, 1),
            "recommendation": self.recommendation
        }


@dataclass 
class ExcelExtractionResult:
    """Result of Excel file extraction"""
    success: bool
    file_path: str
    file_name: str = ""
    profiles: List[ProfileQuantity] = field(default_factory=list)
    
    # Categorized totals
    total_estrutura_kg: float = 0.0
    total_madres_cobertura_kg: float = 0.0
    total_madres_fachada_kg: float = 0.0
    total_omega_kg: float = 0.0
    total_outros_kg: float = 0.0
    total_geral_kg: float = 0.0
    total_area_m2: float = 0.0
    
    # Profile counts
    total_pieces: int = 0
    
    confidence: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duplicate_warnings: List[DuplicateWarning] = field(default_factory=list)
    file_format: str = "unknown"
    
    # Revestimentos (cladding) items
    revestimentos: List['RevestimentoItem'] = field(default_factory=list)
    is_revestimentos_file: bool = False
    
    # Sanity check results
    sanity_checks: List['SanityCheckResult'] = field(default_factory=list)
    sanity_check_passed: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_format": self.file_format,
            "profiles": [p.to_dict() for p in self.profiles],
            "summary": {
                "estrutura_metalica_kg": round(self.total_estrutura_kg, 2),
                "madres_cobertura_kg": round(self.total_madres_cobertura_kg, 2),
                "madres_fachada_kg": round(self.total_madres_fachada_kg, 2),
                "omega_kg": round(self.total_omega_kg, 2),
                "madres_galvanizadas_kg": round(self.total_madres_cobertura_kg + self.total_madres_fachada_kg + self.total_omega_kg, 2),
                "outros_kg": round(self.total_outros_kg, 2),
                "total_geral_kg": round(self.total_geral_kg, 2),
                "total_area_m2": round(self.total_area_m2, 2),
                "total_pieces": self.total_pieces
            },
            "confidence": round(self.confidence, 4),
            "errors": self.errors,
            "warnings": self.warnings,
            "duplicate_warnings": [d.to_dict() for d in self.duplicate_warnings],
            "revestimentos": [r.to_dict() for r in self.revestimentos] if self.revestimentos else [],
            "is_revestimentos_file": self.is_revestimentos_file,
            "sanity_checks": [sc.to_dict() for sc in self.sanity_checks] if self.sanity_checks else [],
            "sanity_check_passed": self.sanity_check_passed
        }


@dataclass
class MergedExcelResult:
    """Result of merging multiple Excel files with duplicate detection"""
    success: bool
    files_processed: int = 0
    
    # Merged totals (after duplicate removal)
    total_estrutura_kg: float = 0.0
    total_madres_kg: float = 0.0  # All madres (cobertura + fachada + omega)
    total_omega_kg: float = 0.0
    total_outros_kg: float = 0.0
    total_geral_kg: float = 0.0
    
    # All profiles (deduplicated)
    profiles: List[ProfileQuantity] = field(default_factory=list)
    
    # Revestimentos (merged from all files)
    revestimentos: List['RevestimentoItem'] = field(default_factory=list)
    has_revestimentos: bool = False
    
    # Warnings
    duplicate_warnings: List[DuplicateWarning] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    
    # User validation required
    requires_user_validation: bool = False
    validation_message: str = ""
    
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "files_processed": self.files_processed,
            "summary": {
                "estrutura_metalica_kg": round(self.total_estrutura_kg, 2),
                "madres_galvanizadas_kg": round(self.total_madres_kg, 2),
                "omega_kg": round(self.total_omega_kg, 2),
                "outros_kg": round(self.total_outros_kg, 2),
                "total_geral_kg": round(self.total_geral_kg, 2)
            },
            "profiles": [p.to_dict() for p in self.profiles],
            "duplicate_warnings": [d.to_dict() for d in self.duplicate_warnings],
            "validation_warnings": self.validation_warnings,
            "requires_user_validation": self.requires_user_validation,
            "validation_message": self.validation_message,
            "confidence": round(self.confidence, 4),
            "revestimentos": [r.to_dict() for r in self.revestimentos] if self.revestimentos else [],
            "has_revestimentos": self.has_revestimentos
        }


class FLYSTEELExcelParser:
    """
    Parser for FLYSTEEL cost structure Excel files and Tekla material lists.
    
    Supports:
    1. .xlsx files with FLYSTEEL cost structure format
    2. .xls HTML files (Tekla/FLYSTEEL material list exports) with QTD × Peso logic
    3. Duplicate detection between files
    4. OMEGA profile categorization
    """
    
    # Profile categories based on designation patterns
    ESTRUTURA_PATTERNS = [
        r'^IPE\s*\d+',
        r'^HEA\s*\d+',
        r'^HEB\s*\d+',
        r'^HEM\s*\d+',
        r'^UPN\s*\d+',
        r'^TUBO',
        r'^CF[A-Z]+',  # Cold-formed sections like CFCHS
        r'^CHAPA\s*(PRETA|XADREZ)?',
        r'^PL\s*\d+',  # Plates
        r'PILAR',
        r'VIGA',
        r'TRAVESSA',
        r'RHS\d+',
        r'SHS\d+',
        r'CHS\d+',
    ]
    
    MADRES_COBERTURA_PATTERNS = [
        r'^MADRE.*COB',
        r'^Z\s*\d+.*COB',
        r'^C\s*\d+\*\d+.*COB',
        r'FRIBROC',  # FRIBROC profiles for roofing
        r'COBERTURA',
    ]
    
    MADRES_FACHADA_PATTERNS = [
        r'^MADRE.*FACH',
        r'^Z\s*\d+.*FACH',
        r'^C\s*\d+\*\d+.*FACH',
        r'FACHADA',
    ]
    
    OMEGA_PATTERNS = [
        r'OMEGA\s*\d*',
        r'^Ω\s*\d+',
    ]
    
    GALVANIZADO_PATTERNS = [
        r'GALVANIZAD[AO]',
        r'^MADRE',
        r'^Z\s*\d+',
        r'^C\s*\d+\*\d+',
        r'GALV',
        r'S280GD',  # Galvanized steel grade
    ]
    
    def __init__(self):
        self.estrutura_regex = [re.compile(p, re.IGNORECASE) for p in self.ESTRUTURA_PATTERNS]
        self.madres_cob_regex = [re.compile(p, re.IGNORECASE) for p in self.MADRES_COBERTURA_PATTERNS]
        self.madres_fach_regex = [re.compile(p, re.IGNORECASE) for p in self.MADRES_FACHADA_PATTERNS]
        self.omega_regex = [re.compile(p, re.IGNORECASE) for p in self.OMEGA_PATTERNS]
        self.galv_regex = [re.compile(p, re.IGNORECASE) for p in self.GALVANIZADO_PATTERNS]
    
    def categorize_profile(self, designation: str, material: str = "", layer: str = "") -> str:
        """Categorize profile as 'estrutura', 'madres_cobertura', 'madres_fachada', 'omega', or 'outros'"""
        if not designation:
            return 'outros'
        
        combined = f"{designation} {material} {layer}"
        
        # Check OMEGA first (most specific for this project)
        for regex in self.omega_regex:
            if regex.search(designation):
                return 'omega'
        
        # Check madres cobertura
        for regex in self.madres_cob_regex:
            if regex.search(combined):
                return 'madres_cobertura'
        
        # Check madres fachada
        for regex in self.madres_fach_regex:
            if regex.search(combined):
                return 'madres_fachada'
        
        # Check galvanized (if not already categorized, treat as madres)
        for regex in self.galv_regex:
            if regex.search(combined):
                # Default galvanized to madres_cobertura if no specific location
                return 'madres_cobertura'
        
        # Check structural steel
        for regex in self.estrutura_regex:
            if regex.search(designation):
                return 'estrutura'
        
        return 'outros'
    
    def detect_file_format(self, file_path: str) -> str:
        """Detect if file is real Excel or HTML-based"""
        path = Path(file_path)
        
        try:
            with open(file_path, 'rb') as f:
                header = f.read(100)
                
                # ZIP magic number (XLSX)
                if header[:4] == b'PK\x03\x04':
                    return 'xlsx'
                
                # OLE magic number (XLS binary)
                if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
                    return 'xls_binary'
                
                # HTML detection
                header_str = header.decode('latin-1', errors='ignore').lower()
                if '<html' in header_str or '<!doctype' in header_str or '<table' in header_str:
                    return 'html_excel'
                
                # XML-based
                if '<?xml' in header_str:
                    return 'xml_excel'
                    
        except Exception:
            pass
        
        # Fallback to extension
        if path.suffix.lower() == '.xlsx':
            return 'xlsx'
        elif path.suffix.lower() == '.xls':
            return 'xls_unknown'
        
        return 'unknown'
    
    def is_revestimentos_file(self, file_path: str) -> bool:
        """Check if file is a Revestimentos (cladding) cost structure file"""
        file_name = Path(file_path).name.lower()
        return 'revestimento' in file_name or 'cobertura' in file_name and 'estrutura de custos' in file_name
    
    def parse_excel(self, file_path: str) -> ExcelExtractionResult:
        """Parse FLYSTEEL Excel cost structure or Tekla material list file"""
        file_name = Path(file_path).name
        result = ExcelExtractionResult(
            success=False,
            file_path=file_path,
            file_name=file_name
        )
        
        # Check if this is a Revestimentos file
        if self.is_revestimentos_file(file_path):
            print(f"[ExcelParser] Detetado ficheiro de Revestimentos: {file_name}")
            return self._parse_revestimentos_xlsx(file_path, result)
        
        # Detect file format
        file_format = self.detect_file_format(file_path)
        result.file_format = file_format
        
        print(f"[ExcelParser] Ficheiro: {file_name}, Formato: {file_format}")
        
        if file_format == 'html_excel':
            return self._parse_tekla_html(file_path, result)
        elif file_format in ['xlsx', 'xml_excel']:
            return self._parse_xlsx(file_path, result)
        elif file_format == 'xls_binary':
            return self._parse_xls_binary(file_path, result)
        else:
            # Try multiple methods
            result.warnings.append(f"Formato desconhecido, tentando múltiplos métodos...")
            
            # Try HTML first (most common for Tekla exports)
            try:
                html_result = self._parse_tekla_html(file_path, result)
                if html_result.success and html_result.profiles:
                    return html_result
            except Exception:
                pass
            
            # Try XLSX
            try:
                xlsx_result = self._parse_xlsx(file_path, result)
                if xlsx_result.success and xlsx_result.profiles:
                    return xlsx_result
            except Exception:
                pass
            
            result.errors.append("Não foi possível ler o ficheiro em nenhum formato suportado")
            return result
    
    def _parse_tekla_html(self, file_path: str, result: ExcelExtractionResult) -> ExcelExtractionResult:
        """
        Parse Tekla HTML-based XLS file with QTD × Peso logic.
        This is the enhanced parser for Tekla material list exports.
        """
        if not HAS_PANDAS:
            result.errors.append("Pandas não instalado. Necessário para ler ficheiros Tekla")
            return result
        
        try:
            # Read file content with latin-1 encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            
            # Parse HTML tables
            dfs = pd.read_html(StringIO(content))
            
            if not dfs:
                result.errors.append("Nenhuma tabela encontrada no ficheiro HTML")
                return result
            
            print(f"[ExcelParser] Encontradas {len(dfs)} tabelas HTML")
            
            # Use the first (main) table
            df = dfs[0]
            
            # Find the header row
            header_row_idx = self._find_tekla_header_row(df)
            
            if header_row_idx is None:
                result.warnings.append("Cabeçalho não encontrado, usando linha 7 por defeito")
                header_row_idx = 7
            
            # Find column indices for Tekla format
            col_mapping = self._find_tekla_columns(df, header_row_idx)
            
            print(f"[ExcelParser] Colunas Tekla mapeadas: {col_mapping}")
            
            if not col_mapping.get('perfil') and not col_mapping.get('peso'):
                result.errors.append("Colunas essenciais (Perfil, Peso) não encontradas")
                return result
            
            # Extract profiles using QTD × Peso logic
            profiles = self._extract_tekla_profiles(df, col_mapping, header_row_idx + 1, result)
            
            result.profiles = profiles
            result.file_name = Path(file_path).name
            
            # Collect raw items for sanity check
            raw_items_for_sanity = [
                {'designation': p.designation, 'quantity': p.total_quantity_kg}
                for p in profiles
            ]
            
            # Set source file for all profiles
            for p in result.profiles:
                p.source_file = result.file_name
            
            # Calculate totals
            self._calculate_totals(result)
            
            # Perform sanity check (Tekla files usually don't have explicit totals)
            self._perform_sanity_check(
                result=result,
                raw_items=raw_items_for_sanity,
                presented_total=None,  # Tekla exports typically don't have totals
                column_name="Peso Total (kg)"
            )
            
            result.success = len(profiles) > 0
            result.file_format = "tekla_html"
            
            if result.success:
                print(f"[ExcelParser] Extraídos {len(profiles)} perfis, Total: {result.total_geral_kg:.2f} kg")
                print(f"[ExcelParser]   - Estrutura: {result.total_estrutura_kg:.2f} kg")
                print(f"[ExcelParser]   - OMEGA: {result.total_omega_kg:.2f} kg")
                print(f"[ExcelParser]   - Madres: {result.total_madres_cobertura_kg + result.total_madres_fachada_kg:.2f} kg")
            
            return result
            
        except Exception as e:
            result.errors.append(f"Erro ao processar Tekla HTML: {str(e)}")
            import traceback
            print(f"[ExcelParser] Erro: {traceback.format_exc()}")
            return result
    
    def _find_tekla_header_row(self, df: 'pd.DataFrame') -> Optional[int]:
        """Find the header row in Tekla HTML table"""
        keywords = ['perfil', 'material', 'qtd', 'peso', 'comp', 'área', 
                   'profile', 'weight', 'length', 'area']
        
        for idx in range(min(15, len(df))):
            row_text = ' '.join(str(v).lower() for v in df.iloc[idx].values if pd.notna(v))
            matches = sum(1 for kw in keywords if kw in row_text)
            if matches >= 3:  # Need at least 3 matches for Tekla format
                return idx
        
        return None
    
    def _find_tekla_columns(self, df: 'pd.DataFrame', header_row_idx: int) -> Dict[str, int]:
        """
        Find column positions in Tekla format.
        Tekla exports have repeated columns - we use the FIRST occurrence.
        """
        col_mapping = {}
        header_row = df.iloc[header_row_idx]
        
        seen_headers = set()
        
        for col_idx, val in enumerate(header_row.values):
            if pd.notna(val):
                val_str = str(val).strip()
                val_lower = val_str.lower()
                
                # Skip if we've already found this header (avoid repeated columns)
                if val_lower in seen_headers:
                    continue
                seen_headers.add(val_lower)
                
                # Map columns
                if 'perfil' in val_lower or 'profile' in val_lower:
                    col_mapping['perfil'] = col_idx
                elif 'material' in val_lower:
                    col_mapping['material'] = col_idx
                elif 'qtd' in val_lower or 'quantidade' in val_lower or val_lower == 'qty':
                    col_mapping['qtd'] = col_idx
                elif ('comp' in val_lower or 'length' in val_lower) and 'mm' in val_lower:
                    col_mapping['comp'] = col_idx
                elif 'área' in val_lower or 'area' in val_lower:
                    col_mapping['area'] = col_idx
                elif 'peso' in val_lower or 'weight' in val_lower:
                    col_mapping['peso'] = col_idx
        
        return col_mapping
    
    def _extract_tekla_profiles(self, df: 'pd.DataFrame', col_mapping: Dict[str, int], 
                                 start_row: int, result: ExcelExtractionResult) -> List[ProfileQuantity]:
        """
        Extract profiles from Tekla format using QTD × Peso logic.
        This correctly calculates total weight as: quantity × weight_per_piece
        """
        profiles = []
        
        perfil_idx = col_mapping.get('perfil', 0)
        material_idx = col_mapping.get('material')
        qtd_idx = col_mapping.get('qtd')
        comp_idx = col_mapping.get('comp')
        area_idx = col_mapping.get('area')
        peso_idx = col_mapping.get('peso')
        
        print(f"[ExcelParser] Extraindo perfis a partir da linha {start_row}")
        print(f"[ExcelParser] Índices: perfil={perfil_idx}, qtd={qtd_idx}, peso={peso_idx}")
        
        for row_idx in range(start_row, len(df)):
            try:
                row = df.iloc[row_idx]
                
                # Get profile name
                perfil = str(row.iloc[perfil_idx]).strip() if perfil_idx is not None else ''
                
                # Skip empty, NaN, or header-like rows
                if not perfil or perfil.lower() in ['perfil', 'profile', 'nan', 'none']:
                    continue
                if any(kw in perfil.lower() for kw in ['projecto', 'local', 'data', 'descrição', 'fs aço', 'pt aço', 'observ']):
                    continue
                
                # Get material
                material = str(row.iloc[material_idx]).strip() if material_idx is not None else ''
                if material.lower() == 'nan':
                    material = ''
                
                # Get quantity (number of pieces)
                qtd = self._extract_number(row.iloc[qtd_idx]) if qtd_idx is not None else 1
                qtd = qtd if qtd and qtd > 0 else 1
                
                # Get weight per piece
                peso_per_piece = self._extract_number(row.iloc[peso_idx]) if peso_idx is not None else 0
                
                # Get length
                comp_mm = self._extract_number(row.iloc[comp_idx]) if comp_idx is not None else 0
                
                # Get area
                area_m2 = self._extract_number(row.iloc[area_idx]) if area_idx is not None else 0
                
                # Skip if no valid weight data
                if peso_per_piece is None or peso_per_piece <= 0:
                    continue
                
                # Calculate total weight: QTD × Peso per piece
                total_weight_kg = qtd * peso_per_piece
                
                # Calculate weight per meter
                comp_m = comp_mm / 1000 if comp_mm and comp_mm > 100 else (comp_mm or 0)
                kg_per_m = peso_per_piece / comp_m if comp_m > 0 else 0
                
                # Categorize profile
                category = self.categorize_profile(perfil, material)
                
                profile = ProfileQuantity(
                    reference=perfil[:20] if len(perfil) > 20 else perfil,
                    designation=perfil,
                    length_ml=comp_m * qtd,  # Total length
                    weight_per_meter=round(kg_per_m, 2),
                    area_per_meter=(area_m2 / comp_m) if comp_m > 0 else 0,
                    total_quantity_kg=total_weight_kg,
                    unit='kg',
                    category=category,
                    material=material,
                    quantity_pcs=int(qtd),
                    weight_per_piece=peso_per_piece
                )
                
                profiles.append(profile)
                
            except Exception as e:
                result.warnings.append(f"Erro na linha {row_idx}: {str(e)}")
                continue
        
        # Aggregate profiles with same designation
        profiles = self._aggregate_profiles(profiles)
        
        return profiles
    
    def _aggregate_profiles(self, profiles: List[ProfileQuantity]) -> List[ProfileQuantity]:
        """Aggregate profiles with same designation and material"""
        aggregated = {}
        
        for p in profiles:
            key = (p.designation, p.material, p.category)
            
            if key in aggregated:
                existing = aggregated[key]
                existing.total_quantity_kg += p.total_quantity_kg
                existing.length_ml += p.length_ml
                existing.quantity_pcs += p.quantity_pcs
            else:
                aggregated[key] = ProfileQuantity(
                    reference=p.reference,
                    designation=p.designation,
                    length_ml=p.length_ml,
                    weight_per_meter=p.weight_per_meter,
                    area_per_meter=p.area_per_meter,
                    total_quantity_kg=p.total_quantity_kg,
                    unit=p.unit,
                    category=p.category,
                    material=p.material,
                    quantity_pcs=p.quantity_pcs,
                    weight_per_piece=p.weight_per_piece,
                    source_file=p.source_file
                )
        
        return list(aggregated.values())
    
    def _parse_xlsx(self, file_path: str, result: ExcelExtractionResult) -> ExcelExtractionResult:
        """Parse standard XLSX file (FLYSTEEL cost structure format)"""
        if not HAS_OPENPYXL:
            result.errors.append("openpyxl não instalado. Necessário para ler ficheiros .xlsx")
            return result
        
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
        except Exception as e:
            result.errors.append(f"Erro ao abrir ficheiro Excel: {str(e)}")
            return result
        
        # Try to find the correct sheet
        sheet = None
        for sheet_name in ['Sheet 1', 'Sheet1', 'Custos', 'Quantidades', 'lista de material']:
            if sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                break
        
        if sheet is None:
            sheet = wb.active
            result.warnings.append(f"Usando folha ativa: {sheet.title}")
        
        # Find header row
        header_row = None
        for row_num in range(1, 15):
            row_values = [str(sheet.cell(row=row_num, column=c).value or '').lower() 
                         for c in range(1, 15)]
            row_text = ' '.join(row_values)
            
            if any(kw in row_text for kw in ['designa', 'referência', 'perfil', 'quantidade']):
                header_row = row_num
                break
        
        if header_row is None:
            header_row = 4
            result.warnings.append("Usando linha de cabeçalho 4 por defeito")
        
        # Detect column positions
        col_mapping = self._detect_columns_xlsx(sheet, header_row)
        
        # Parse data rows and collect raw items for sanity check
        profiles = []
        raw_items_for_sanity = []  # For sanity check
        data_end_row = header_row + 1
        
        for row_num in range(header_row + 1, sheet.max_row + 1):
            try:
                profile = self._parse_xlsx_row(sheet, row_num, col_mapping, result.file_name)
                if profile:
                    profiles.append(profile)
                    data_end_row = row_num
                    
                    # Collect raw data for sanity check
                    raw_items_for_sanity.append({
                        'designation': profile.designation,
                        'quantity': profile.total_quantity_kg
                    })
            except Exception as e:
                result.warnings.append(f"Erro na linha {row_num}: {str(e)}")
                continue
        
        # SANITY CHECK: Look for presented total and verify against calculated sum
        quantity_col = col_mapping.get('quantity', 11)
        presented_total = self._find_presented_total(sheet, quantity_col, data_end_row)
        
        wb.close()
        
        if not profiles:
            result.errors.append("Nenhum perfil válido encontrado no ficheiro Excel")
            return result
        
        result.profiles = self._aggregate_profiles(profiles)
        result.file_name = Path(file_path).name
        result.file_format = "xlsx"
        
        # Calculate totals
        self._calculate_totals(result)
        
        # Perform sanity check on Quantidade column
        self._perform_sanity_check(
            result=result,
            raw_items=raw_items_for_sanity,
            presented_total=presented_total,
            column_name="Quantidade (kg)"
        )
        
        result.success = True
        print(f"[ExcelParser] Extraídos {len(result.profiles)} perfis, Total: {result.total_geral_kg:.2f} kg")
        
        return result
    
    def _detect_columns_xlsx(self, sheet, header_row: int) -> Dict[str, int]:
        """Detect column positions in XLSX"""
        col_mapping = {}
        
        for col in range(1, 30):
            value = str(sheet.cell(row=header_row, column=col).value or '').lower().strip()
            
            if 'referência' in value or value == 'ref':
                col_mapping['reference'] = col
            elif 'designação' in value or 'designa' in value or 'perfil' in value:
                col_mapping['designation'] = col
            elif value == 'ml' or value == 'comprimento' or value == 'comp':
                col_mapping['length'] = col
            elif 'kg/m' in value or 'kgs/m' in value:
                col_mapping['kg_per_m'] = col
            elif 'm2/m' in value or 'm²/m' in value:
                col_mapping['m2_per_m'] = col
            elif value == 'quantidade' or value == 'qtd':
                if 'quantity' not in col_mapping:
                    col_mapping['quantity'] = col
            elif 'unidade' in value or value == 'un':
                col_mapping['unit'] = col
            elif 'material' in value:
                col_mapping['material'] = col
            elif value == 'peso' or value == 'kg':
                col_mapping['weight'] = col
        
        # Default FLYSTEEL columns
        if 'reference' not in col_mapping:
            col_mapping['reference'] = 2
        if 'designation' not in col_mapping:
            col_mapping['designation'] = 4
        if 'length' not in col_mapping:
            col_mapping['length'] = 7
        if 'kg_per_m' not in col_mapping:
            col_mapping['kg_per_m'] = 8
        if 'm2_per_m' not in col_mapping:
            col_mapping['m2_per_m'] = 9
        if 'quantity' not in col_mapping:
            col_mapping['quantity'] = 11
        if 'unit' not in col_mapping:
            col_mapping['unit'] = 12
        
        return col_mapping
    
    def _parse_xlsx_row(self, sheet, row_num: int, col_mapping: Dict[str, int], 
                        source_file: str) -> Optional[ProfileQuantity]:
        """Parse a single XLSX row"""
        reference = str(sheet.cell(row=row_num, column=col_mapping.get('reference', 2)).value or '')
        designation = str(sheet.cell(row=row_num, column=col_mapping.get('designation', 4)).value or '')
        
        if not designation.strip() or designation.lower() == 'none':
            for col in range(1, 10):
                val = str(sheet.cell(row=row_num, column=col).value or '')
                if val and any(p in val.upper() for p in ['IPE', 'HEA', 'HEB', 'TUBO', 'CHAPA', 'UPN', 'CF', 'OMEGA']):
                    designation = val
                    break
        
        if not designation.strip() or designation.lower() == 'none':
            return None
        
        if any(kw in designation.lower() for kw in ['designação', 'designa', 'total', 'subtotal', 'referência']):
            return None
        
        length_ml = self._extract_number(sheet.cell(row=row_num, column=col_mapping.get('length', 7)).value)
        kg_per_m = self._extract_number(sheet.cell(row=row_num, column=col_mapping.get('kg_per_m', 8)).value)
        m2_per_m = self._extract_number(sheet.cell(row=row_num, column=col_mapping.get('m2_per_m', 9)).value) or 0
        quantity_kg = self._extract_number(sheet.cell(row=row_num, column=col_mapping.get('quantity', 11)).value)
        weight = self._extract_number(sheet.cell(row=row_num, column=col_mapping.get('weight', 11)).value)
        unit = str(sheet.cell(row=row_num, column=col_mapping.get('unit', 12)).value or 'kg')
        material = str(sheet.cell(row=row_num, column=col_mapping.get('material', 3)).value or '')
        
        if (length_ml is None or length_ml <= 0) and (quantity_kg is None or quantity_kg <= 0) and (weight is None or weight <= 0):
            return None
        
        if quantity_kg and quantity_kg > 0:
            total_kg = quantity_kg
        elif weight and weight > 0:
            total_kg = weight
        elif length_ml and kg_per_m:
            total_kg = length_ml * kg_per_m
        else:
            return None
        
        category = self.categorize_profile(designation, material)
        
        return ProfileQuantity(
            reference=reference.strip(),
            designation=designation.strip(),
            length_ml=length_ml or 0,
            weight_per_meter=kg_per_m or 0,
            area_per_meter=m2_per_m,
            total_quantity_kg=total_kg,
            unit=unit.strip() or 'kg',
            category=category,
            material=material.strip(),
            source_file=source_file
        )
    
    def _parse_xls_binary(self, file_path: str, result: ExcelExtractionResult) -> ExcelExtractionResult:
        """Parse binary XLS file using pandas"""
        if not HAS_PANDAS:
            result.errors.append("Pandas não instalado")
            return result
        
        try:
            df = pd.read_excel(file_path, sheet_name=0, engine='xlrd')
            
            header_row_idx = self._find_tekla_header_row(df)
            
            if header_row_idx is not None:
                new_headers = df.iloc[header_row_idx].astype(str).tolist()
                df = df.iloc[header_row_idx + 1:].reset_index(drop=True)
                df.columns = new_headers
            
            # Use standard parsing
            result.file_format = "xls_binary"
            return result
            
        except Exception as e:
            result.errors.append(f"Erro ao processar XLS binário: {str(e)}")
            return result
    
    def _parse_revestimentos_xlsx(self, file_path: str, result: ExcelExtractionResult) -> ExcelExtractionResult:
        """
        Parse FLYSTEEL Revestimentos (Cladding) cost structure file.
        
        Columns:
        - B (1): Referência
        - D (3): Designação
        - G (6): ml (linear meters)
        - H (7): Kgs/ml
        - I (8): m2/ml
        - K (10): Quantidade
        - L (11): Unidade (m2, ml, un)
        """
        if not HAS_OPENPYXL:
            result.errors.append("openpyxl não instalado")
            return result
        
        file_name = Path(file_path).name
        result.is_revestimentos_file = True
        result.file_format = "xlsx_revestimentos"
        
        # Determine category from filename
        file_name_lower = file_name.lower()
        if 'cobertura' in file_name_lower:
            default_category = 'cobertura'
        elif 'fachada' in file_name_lower:
            default_category = 'fachada'
        else:
            default_category = 'revestimentos'
        
        print(f"[ExcelParser] Parsing Revestimentos: {file_name}, Categoria: {default_category}")
        
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active
            
            # Find header row (contains 'Designação', 'ml', 'Quantidade', 'Unidade')
            header_row = None
            for row_num in range(1, 15):
                row_values = [str(sheet.cell(row=row_num, column=c).value or '').lower().strip() 
                             for c in range(1, 15)]
                row_text = ' '.join(row_values)
                
                if 'designação' in row_text and ('quantidade' in row_text or 'unidade' in row_text):
                    header_row = row_num
                    print(f"[ExcelParser] Header encontrado na linha {row_num}: {row_values[:12]}")
                    break
            
            if header_row is None:
                header_row = 4  # Default for FLYSTEEL format
                result.warnings.append("Cabeçalho não encontrado, usando linha 4 por defeito")
            
            # Map columns based on header
            col_mapping = {}
            for col in range(1, 20):
                val = str(sheet.cell(row=header_row, column=col).value or '').lower().strip()
                
                if 'referência' in val or val == 'ref':
                    col_mapping['reference'] = col
                elif 'designação' in val or 'designa' in val:
                    col_mapping['designation'] = col
                elif val == 'ml' or val == 'comprimento':
                    col_mapping['ml'] = col
                elif 'kgs/ml' in val or 'kg/ml' in val:
                    col_mapping['kg_per_ml'] = col
                elif 'm2/ml' in val or 'm²/ml' in val:
                    col_mapping['m2_per_ml'] = col
                elif 'quantidade' in val or val == 'qtd':
                    col_mapping['quantity'] = col
                elif 'unidade' in val or val == 'un':
                    col_mapping['unit'] = col
            
            # Default FLYSTEEL positions
            if 'reference' not in col_mapping:
                col_mapping['reference'] = 2
            if 'designation' not in col_mapping:
                col_mapping['designation'] = 4
            if 'ml' not in col_mapping:
                col_mapping['ml'] = 7
            if 'kg_per_ml' not in col_mapping:
                col_mapping['kg_per_ml'] = 8
            if 'm2_per_ml' not in col_mapping:
                col_mapping['m2_per_ml'] = 9
            if 'quantity' not in col_mapping:
                col_mapping['quantity'] = 11
            if 'unit' not in col_mapping:
                col_mapping['unit'] = 12
            
            print(f"[ExcelParser] Colunas mapeadas: {col_mapping}")
            
            # Parse data rows
            revestimentos = []
            
            for row_num in range(header_row + 1, sheet.max_row + 1):
                try:
                    designation = str(sheet.cell(row=row_num, column=col_mapping['designation']).value or '').strip()
                    
                    # Skip empty or header-like rows
                    if not designation or designation.lower() in ['designação', 'none', 'nan', '']:
                        continue
                    
                    # Skip total/subtotal rows
                    if any(kw in designation.lower() for kw in ['total', 'subtotal', 'soma']):
                        continue
                    
                    reference = str(sheet.cell(row=row_num, column=col_mapping['reference']).value or '').strip()
                    quantity = self._extract_number(sheet.cell(row=row_num, column=col_mapping['quantity']).value)
                    unit = str(sheet.cell(row=row_num, column=col_mapping['unit']).value or 'un').strip().lower()
                    kg_per_ml = self._extract_number(sheet.cell(row=row_num, column=col_mapping['kg_per_ml']).value) or 0
                    m2_per_ml = self._extract_number(sheet.cell(row=row_num, column=col_mapping['m2_per_ml']).value) or 0
                    
                    # Skip if no quantity
                    if quantity is None or quantity <= 0:
                        continue
                    
                    # Normalize unit
                    if unit in ['m²', 'm2']:
                        unit = 'm2'
                    elif unit in ['metro linear', 'metros lineares']:
                        unit = 'ml'
                    elif unit in ['unidade', 'unidades', 'pcs']:
                        unit = 'un'
                    
                    # Categorize item more specifically
                    designation_lower = designation.lower()
                    
                    # ACESSÓRIOS - items que não são área principal
                    # Lã de rocha e isolamento são complementos, não área de painel
                    if 'parafuso' in designation_lower:
                        category = 'acessorios'
                    elif 'lã' in designation_lower or 'la de rocha' in designation_lower:
                        category = 'acessorios'  # Isolamento é acessório, não área
                    elif 'isolamento' in designation_lower or 'isolante' in designation_lower:
                        category = 'acessorios'
                    elif 'vedante' in designation_lower or 'silicone' in designation_lower:
                        category = 'acessorios'
                    elif 'fita' in designation_lower or 'cola' in designation_lower:
                        category = 'acessorios'
                    # CALEIROS - categoria específica
                    elif 'caleiro' in designation_lower or 'caleira' in designation_lower:
                        category = 'caleiros'
                    elif 'tubo de queda' in designation_lower or 'tubo queda' in designation_lower:
                        category = 'caleiros'
                    # REMATES - mantém categoria do ficheiro (importante: antes de painéis!)
                    elif 'remate' in designation_lower:
                        category = default_category
                    # PAINÉIS - detectar por código de produto
                    elif any(x in designation_lower for x in ['p5g', 'p5l', 'pcp']):
                        category = 'cobertura'  # Painéis de cobertura específicos
                    elif any(x in designation_lower for x in ['pf1', 'pf2', 'pfl']):
                        category = 'fachada'  # Painéis de fachada específicos
                    elif any(x in designation_lower for x in ['pm1', 'pm2']):
                        category = 'divisorias'  # Painéis de divisórias específicos
                    # COBERTURA - por palavras-chave
                    elif 'painel' in designation_lower and 'cobertura' in designation_lower:
                        category = 'cobertura'
                    elif 'cume' in designation_lower or 'anticume' in designation_lower:
                        category = 'cobertura'
                    # FACHADA - por palavras-chave
                    elif 'painel' in designation_lower and 'fachada' in designation_lower:
                        category = 'fachada'
                    # DIVISÓRIAS - por palavras-chave
                    elif 'divisoria' in designation_lower or 'divisória' in designation_lower:
                        category = 'divisorias'
                    # Claraboias/áreas de luz
                    elif 'area de luz' in designation_lower or 'claraboia' in designation_lower:
                        category = 'cobertura'
                    else:
                        category = default_category
                    
                    item = RevestimentoItem(
                        reference=reference if reference.lower() != 'nan' else '',
                        designation=designation,
                        quantity=quantity,
                        unit=unit,
                        category=category,
                        kg_per_ml=kg_per_ml,
                        m2_per_ml=m2_per_ml,
                        source_file=file_name
                    )
                    
                    revestimentos.append(item)
                    print(f"[ExcelParser]   + {designation}: {quantity} {unit} ({category})")
                    
                except Exception as e:
                    result.warnings.append(f"Erro na linha {row_num}: {str(e)}")
                    continue
            
            # Collect raw items for sanity check
            raw_items_for_sanity = [
                {'designation': r.designation, 'quantity': r.quantity}
                for r in revestimentos
            ]
            
            # Look for presented total
            quantity_col = col_mapping.get('quantity', 11)
            presented_total = self._find_presented_total(sheet, quantity_col, header_row + len(revestimentos) + 1)
            
            wb.close()
            
            result.revestimentos = revestimentos
            result.success = len(revestimentos) > 0
            result.confidence = 0.90 if result.success else 0.0
            
            # Perform sanity check on Quantidade column
            self._perform_sanity_check(
                result=result,
                raw_items=raw_items_for_sanity,
                presented_total=presented_total,
                column_name="Quantidade Revestimentos"
            )
            
            print(f"[ExcelParser] Extraídos {len(revestimentos)} itens de revestimentos")
            
            return result
            
        except Exception as e:
            result.errors.append(f"Erro ao processar Revestimentos: {str(e)}")
            import traceback
            print(f"[ExcelParser] Erro: {traceback.format_exc()}")
            return result
    
    def _calculate_totals(self, result: ExcelExtractionResult):
        """Calculate totals from profiles by category"""
        result.total_estrutura_kg = sum(p.total_quantity_kg for p in result.profiles if p.category == 'estrutura')
        result.total_madres_cobertura_kg = sum(p.total_quantity_kg for p in result.profiles if p.category == 'madres_cobertura')
        result.total_madres_fachada_kg = sum(p.total_quantity_kg for p in result.profiles if p.category == 'madres_fachada')
        result.total_omega_kg = sum(p.total_quantity_kg for p in result.profiles if p.category == 'omega')
        result.total_outros_kg = sum(p.total_quantity_kg for p in result.profiles if p.category == 'outros')
        
        result.total_geral_kg = (
            result.total_estrutura_kg + 
            result.total_madres_cobertura_kg + 
            result.total_madres_fachada_kg + 
            result.total_omega_kg + 
            result.total_outros_kg
        )
        
        result.total_pieces = sum(p.quantity_pcs for p in result.profiles)
        
        # Calculate total area
        result.total_area_m2 = sum(p.area_per_meter * p.length_ml for p in result.profiles if p.area_per_meter > 0)
        
        # Calculate confidence based on data quality
        valid_profiles = len([p for p in result.profiles if p.total_quantity_kg > 0])
        has_omega = result.total_omega_kg > 0
        has_estrutura = result.total_estrutura_kg > 0
        
        base_confidence = 0.85
        if valid_profiles > 5:
            base_confidence += 0.05
        if has_omega and has_estrutura:
            base_confidence += 0.05
        
        result.confidence = min(0.99, base_confidence)
    
    def _extract_number(self, value: Any) -> Optional[float]:
        """Extract numeric value from cell"""
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return float(value)
        
        value_str = str(value).strip()
        if not value_str or value_str.lower() == 'nan':
            return None
        
        # Remove units and formatting
        value_str = re.sub(r'[^\d.,\-]', '', value_str)
        
        if not value_str:
            return None
        
        # Handle European format
        if ',' in value_str and '.' not in value_str:
            value_str = value_str.replace(',', '.')
        elif ',' in value_str and '.' in value_str:
            value_str = value_str.replace(',', '')
        
        try:
            return float(value_str)
        except ValueError:
            return None
    
    def _perform_sanity_check(self, result: ExcelExtractionResult, 
                               raw_items: List[Dict], 
                               presented_total: float = None,
                               column_name: str = "Quantidade") -> None:
        """
        Perform sanity check: verify sum of individual Quantidade values matches totals.
        Always prefer calculated sum over presented totals.
        
        Args:
            result: ExcelExtractionResult to update with sanity check results
            raw_items: List of dicts with 'designation' and 'quantity' keys
            presented_total: Any total value found in the file (optional)
            column_name: Name of the column being checked
        """
        if not raw_items:
            return
        
        # Calculate sum of individual quantities
        calculated_sum = sum(item.get('quantity', 0) for item in raw_items if item.get('quantity'))
        items_count = len([item for item in raw_items if item.get('quantity')])
        
        # Determine if there's a discrepancy
        if presented_total and presented_total > 0:
            difference = abs(calculated_sum - presented_total)
            difference_pct = (difference / max(calculated_sum, presented_total)) * 100 if max(calculated_sum, presented_total) > 0 else 0
            
            # Check passes if difference is less than 1%
            passed = difference_pct < 1.0
            
            if not passed:
                warning_message = (
                    f"DISCREPÂNCIA DETETADA: Soma calculada ({calculated_sum:.2f}) difere do total "
                    f"apresentado ({presented_total:.2f}) em {difference_pct:.1f}%. "
                    f"A APP utiliza a SOMA DOS VALORES INDIVIDUAIS ({calculated_sum:.2f}) como valor correto."
                )
                result.warnings.append(f"[SANITY CHECK] {warning_message}")
            else:
                warning_message = f"Verificação OK: {items_count} itens, soma = {calculated_sum:.2f}"
        else:
            # No presented total - just log the calculated sum
            passed = True
            difference = 0
            difference_pct = 0
            warning_message = f"Soma calculada de {items_count} itens: {calculated_sum:.2f} (sem total de referência)"
        
        # Create sanity check result - ALWAYS use calculated_sum
        sanity_result = SanityCheckResult(
            passed=passed,
            column_name=column_name,
            calculated_sum=calculated_sum,
            presented_total=presented_total or 0,
            difference=difference if presented_total else 0,
            difference_pct=difference_pct if presented_total else 0,
            used_value=calculated_sum,  # Always prefer calculated sum
            warning_message=warning_message,
            items_checked=items_count
        )
        
        result.sanity_checks.append(sanity_result)
        
        if not passed:
            result.sanity_check_passed = False
            # Reduce confidence when sanity check fails
            result.confidence = max(0.5, result.confidence - 0.15)
        
        print(f"[SanityCheck] {column_name}: {warning_message}")
    
    def _find_presented_total(self, sheet, column_idx: int, data_end_row: int) -> Optional[float]:
        """
        Look for a total/subtotal value in the Excel sheet.
        Searches for cells containing 'total', 'subtotal', 'soma' near the quantity column.
        """
        try:
            # Search from data_end_row to end of sheet for total rows
            for row in range(data_end_row, min(data_end_row + 10, sheet.max_row + 1)):
                for col in range(1, min(column_idx + 5, 15)):
                    cell_val = str(sheet.cell(row=row, column=col).value or '').lower()
                    if any(kw in cell_val for kw in ['total', 'subtotal', 'soma']):
                        # Found a total label - get the value from the quantity column
                        total_val = sheet.cell(row=row, column=column_idx).value
                        if total_val and isinstance(total_val, (int, float)):
                            return float(total_val)
            
            return None
        except Exception:
            return None


class ExcelMerger:
    """
    Merges multiple Excel extraction results with duplicate detection.
    Compares with PDF data and provides validation warnings.
    """
    
    def __init__(self):
        self.parser = FLYSTEELExcelParser()
    
    def merge_excel_results(self, results: List[ExcelExtractionResult], 
                            pdf_quantities: Dict[str, float] = None) -> MergedExcelResult:
        """
        Merge multiple Excel results, detect duplicates, and compare with PDF.
        
        Args:
            results: List of ExcelExtractionResult from different files
            pdf_quantities: Optional dict with PDF-extracted quantities for comparison
        """
        merged = MergedExcelResult(success=False, files_processed=len(results))
        
        if not results:
            return merged
        
        # Collect all profiles by category
        estrutura_by_file: Dict[str, float] = {}
        omega_by_file: Dict[str, float] = {}
        madres_by_file: Dict[str, float] = {}
        
        all_profiles = []
        
        for r in results:
            if not r.success:
                continue
            
            file_name = r.file_name or Path(r.file_path).name
            
            estrutura_by_file[file_name] = r.total_estrutura_kg
            omega_by_file[file_name] = r.total_omega_kg
            madres_by_file[file_name] = r.total_madres_cobertura_kg + r.total_madres_fachada_kg
            
            all_profiles.extend(r.profiles)
        
        # Detect duplicates - files with similar values
        duplicate_warnings = self._detect_duplicates(estrutura_by_file, "Estrutura Metálica")
        duplicate_warnings.extend(self._detect_duplicates(omega_by_file, "OMEGA"))
        
        merged.duplicate_warnings = duplicate_warnings
        
        # Determine final values - if duplicates detected, use highest unique value
        unique_files_estrutura = self._get_unique_files(estrutura_by_file)
        unique_files_omega = self._get_unique_files(omega_by_file)
        unique_files_madres = self._get_unique_files(madres_by_file)
        
        merged.total_estrutura_kg = sum(estrutura_by_file[f] for f in unique_files_estrutura)
        merged.total_omega_kg = sum(omega_by_file[f] for f in unique_files_omega)
        merged.total_madres_kg = sum(madres_by_file[f] for f in unique_files_madres) + merged.total_omega_kg
        
        # Filter profiles from unique files only
        unique_files = set(unique_files_estrutura) | set(unique_files_omega) | set(unique_files_madres)
        merged.profiles = [p for p in all_profiles if p.source_file in unique_files]
        
        # Aggregate outros
        merged.total_outros_kg = sum(p.total_quantity_kg for p in merged.profiles if p.category == 'outros')
        
        # Calculate total
        merged.total_geral_kg = merged.total_estrutura_kg + merged.total_madres_kg + merged.total_outros_kg
        
        # Collect revestimentos from all files
        all_revestimentos = []
        for r in results:
            if r.revestimentos:
                all_revestimentos.extend(r.revestimentos)
        
        merged.revestimentos = all_revestimentos
        merged.has_revestimentos = len(all_revestimentos) > 0
        
        if merged.has_revestimentos:
            print(f"[ExcelMerger] Total Revestimentos: {len(all_revestimentos)} itens")
        
        # Compare with PDF if available
        if pdf_quantities:
            validation_warnings = self._compare_with_pdf(merged, pdf_quantities)
            merged.validation_warnings = validation_warnings
        
        # Determine if user validation is required
        if duplicate_warnings:
            merged.requires_user_validation = True
            merged.validation_message = (
                f"Detetados {len(duplicate_warnings)} ficheiros com dados duplicados. "
                "Por favor valide se os valores foram corretamente consolidados. "
                "A app assumiu que ficheiros com valores idênticos são duplicados."
            )
        
        # Calculate confidence
        if merged.total_geral_kg > 0 or merged.has_revestimentos:
            merged.success = True
            merged.confidence = 0.90 - (0.05 * len(duplicate_warnings))
        
        return merged
    
    def _detect_duplicates(self, values_by_file: Dict[str, float], category: str) -> List[DuplicateWarning]:
        """Detect files with duplicate/similar values"""
        warnings = []
        files = list(values_by_file.keys())
        
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                file1, file2 = files[i], files[j]
                val1, val2 = values_by_file[file1], values_by_file[file2]
                
                if val1 == 0 and val2 == 0:
                    continue
                
                # Check if values are identical or very similar (within 15% for structure, 5% for OMEGA)
                if val1 > 0 and val2 > 0:
                    diff_pct = abs(val1 - val2) / max(val1, val2) * 100
                    
                    # Use different thresholds for different categories
                    threshold = 5 if "OMEGA" in category else 15
                    
                    if diff_pct < threshold:
                        warnings.append(DuplicateWarning(
                            profile_type=category,
                            file1=file1,
                            file2=file2,
                            value1=val1,
                            value2=val2,
                            difference_pct=diff_pct,
                            recommendation=(
                                f"Os ficheiros '{file1}' e '{file2}' têm valores de {category} "
                                f"semelhantes ({val1:.2f} vs {val2:.2f}, diferença {diff_pct:.1f}%). "
                                "Podem conter dados sobrepostos - a app utilizará apenas um deles."
                            )
                        ))
        
        return warnings
    
    def _get_unique_files(self, values_by_file: Dict[str, float], threshold_pct: float = 15.0) -> List[str]:
        """Get list of unique files (removing duplicates based on similarity threshold)"""
        if not values_by_file:
            return []
        
        # Group files by similar values
        groups = []
        used = set()
        
        files = list(values_by_file.keys())
        
        for f in files:
            if f in used:
                continue
            
            group = [f]
            val = values_by_file[f]
            
            for other in files:
                if other != f and other not in used:
                    other_val = values_by_file[other]
                    if val > 0 and other_val > 0:
                        diff_pct = abs(val - other_val) / max(val, other_val) * 100
                        if diff_pct < threshold_pct:
                            group.append(other)
            
            # Mark all in group as used
            for g in group:
                used.add(g)
            
            # PRIORITY: Select best file from duplicate group
            # 1. "Estrutura de Custos" files (commercial quotes) - HIGHEST priority
            # 2. Files with largest value (technical exports)
            best_file = self._select_priority_file(group, values_by_file)
            groups.append(best_file)
        
        return groups
    
    def _select_priority_file(self, group: List[str], values_by_file: Dict[str, float]) -> str:
        """
        Select the best file from a group of duplicates.
        Priority order:
        1. "Estrutura de Custos" files (commercial/quote files) - most accurate
        2. Files with "custos" in name
        3. If no priority files, use the one with highest value
        """
        if len(group) == 1:
            return group[0]
        
        # Priority 1: "Estrutura de Custos" files (exact commercial quotes)
        for f in group:
            f_lower = f.lower()
            if 'estrutura de custos' in f_lower or 'estrutura_de_custos' in f_lower:
                print(f"[ExcelMerger] Priorizado ficheiro comercial: {f}")
                return f
        
        # Priority 2: Files with "custos" in name
        for f in group:
            if 'custos' in f.lower():
                print(f"[ExcelMerger] Priorizado ficheiro de custos: {f}")
                return f
        
        # Priority 3: .xlsx over .xls (more modern format)
        xlsx_files = [f for f in group if f.endswith('.xlsx')]
        xls_files = [f for f in group if f.endswith('.xls') and not f.endswith('.xlsx')]
        
        if xlsx_files:
            # Among xlsx, pick highest value
            best = max(xlsx_files, key=lambda x: values_by_file.get(x, 0))
            print(f"[ExcelMerger] Selecionado ficheiro XLSX: {best}")
            return best
        
        # Fallback: highest value
        best = max(group, key=lambda x: values_by_file.get(x, 0))
        print(f"[ExcelMerger] Selecionado por maior valor: {best}")
        return best
    
    def _compare_with_pdf(self, merged: MergedExcelResult, 
                          pdf_quantities: Dict[str, float]) -> List[str]:
        """Compare Excel values with PDF-extracted quantities"""
        warnings = []
        
        pdf_estrutura = pdf_quantities.get('estrutura_metalica_kg', 0)
        pdf_omega = pdf_quantities.get('omega_kg', 0)
        pdf_total = pdf_quantities.get('total_geral_kg', 0)
        
        # Compare estrutura
        if pdf_estrutura > 0 and merged.total_estrutura_kg > 0:
            diff_pct = abs(merged.total_estrutura_kg - pdf_estrutura) / max(merged.total_estrutura_kg, pdf_estrutura) * 100
            if diff_pct > 10:
                warnings.append(
                    f"Discrepância na Estrutura Metálica: Excel={merged.total_estrutura_kg:.2f}kg, "
                    f"PDF={pdf_estrutura:.2f}kg (diferença de {diff_pct:.1f}%). "
                    f"Os valores do Excel têm prioridade."
                )
        
        # Compare omega
        if pdf_omega > 0 and merged.total_omega_kg > 0:
            diff_pct = abs(merged.total_omega_kg - pdf_omega) / max(merged.total_omega_kg, pdf_omega) * 100
            if diff_pct > 10:
                warnings.append(
                    f"Discrepância no OMEGA: Excel={merged.total_omega_kg:.2f}kg, "
                    f"PDF={pdf_omega:.2f}kg (diferença de {diff_pct:.1f}%). "
                    f"Os valores do Excel têm prioridade."
                )
        
        return warnings


def extract_steel_quantities_from_excel(file_path: str) -> Dict[str, Any]:
    """
    Main function to extract steel quantities from FLYSTEEL/Tekla Excel file.
    Returns structured data for budget calculation.
    """
    parser = FLYSTEELExcelParser()
    result = parser.parse_excel(file_path)
    return result.to_dict()


def merge_excel_extractions(results: List[Dict[str, Any]], 
                            pdf_quantities: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Merge multiple Excel extraction results with duplicate detection.
    
    Args:
        results: List of extraction result dicts
        pdf_quantities: Optional PDF-extracted quantities for comparison
    
    Returns:
        Merged result with duplicate warnings and validation info
    """
    # Convert dicts back to ExcelExtractionResult objects
    extraction_results = []
    
    for r in results:
        if r.get('success'):
            er = ExcelExtractionResult(
                success=True,
                file_path=r.get('file_path', ''),
                file_name=r.get('file_name', ''),
                file_format=r.get('file_format', 'unknown'),
                confidence=r.get('confidence', 0.9)
            )
            
            summary = r.get('summary', {})
            er.total_estrutura_kg = summary.get('estrutura_metalica_kg', 0)
            er.total_madres_cobertura_kg = summary.get('madres_cobertura_kg', 0)
            er.total_madres_fachada_kg = summary.get('madres_fachada_kg', 0)
            er.total_omega_kg = summary.get('omega_kg', 0)
            er.total_outros_kg = summary.get('outros_kg', 0)
            er.total_geral_kg = summary.get('total_geral_kg', 0)
            
            # Recreate profiles
            for p in r.get('profiles', []):
                profile = ProfileQuantity(
                    reference=p.get('reference', ''),
                    designation=p.get('designation', ''),
                    length_ml=p.get('length_ml', 0),
                    weight_per_meter=p.get('weight_per_meter', 0),
                    area_per_meter=p.get('area_per_meter', 0),
                    total_quantity_kg=p.get('total_quantity_kg', 0),
                    unit=p.get('unit', 'kg'),
                    category=p.get('category', 'outros'),
                    material=p.get('material', ''),
                    quantity_pcs=p.get('quantity_pcs', 1),
                    weight_per_piece=p.get('weight_per_piece', 0),
                    source_file=p.get('source_file', er.file_name)
                )
                er.profiles.append(profile)
            
            # Recreate revestimentos
            er.is_revestimentos_file = r.get('is_revestimentos_file', False)
            for rev in r.get('revestimentos', []):
                revestimento = RevestimentoItem(
                    reference=rev.get('reference', ''),
                    designation=rev.get('designation', ''),
                    quantity=rev.get('quantity', 0),
                    unit=rev.get('unit', 'un'),
                    category=rev.get('category', 'revestimentos'),
                    kg_per_ml=rev.get('kg_per_ml', 0),
                    m2_per_ml=rev.get('m2_per_ml', 0),
                    source_file=rev.get('source_file', er.file_name)
                )
                er.revestimentos.append(revestimento)
            
            extraction_results.append(er)
    
    merger = ExcelMerger()
    merged = merger.merge_excel_results(extraction_results, pdf_quantities)
    
    return merged.to_dict()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_files = sys.argv[1:]
    else:
        test_files = [
            "/workspace/user_input_files/FS_aço_lista_material.xls",
            "/workspace/user_input_files/PT_aço_lista_material.xls",
            "/workspace/user_input_files/Estrutura de custos.xlsx"
        ]
    
    all_results = []
    
    for test_file in test_files:
        print(f"\n{'='*60}")
        print(f"Testando: {test_file}")
        print('='*60)
        
        result = extract_steel_quantities_from_excel(test_file)
        all_results.append(result)
        
        print(f"\nSuccess: {result['success']}")
        print(f"Format: {result['file_format']}")
        print(f"Confidence: {result['confidence']:.1%}")
        print(f"\n=== SUMMARY ===")
        print(f"Estrutura Metálica: {result['summary']['estrutura_metalica_kg']:,.2f} kg")
        print(f"OMEGA: {result['summary']['omega_kg']:,.2f} kg")
        print(f"Madres Galvanizadas: {result['summary']['madres_galvanizadas_kg']:,.2f} kg")
        print(f"Outros: {result['summary']['outros_kg']:,.2f} kg")
        print(f"TOTAL: {result['summary']['total_geral_kg']:,.2f} kg")
        print(f"Total Peças: {result['summary']['total_pieces']}")
    
    # Test merging
    if len(all_results) > 1:
        print(f"\n{'='*60}")
        print("MERGING ALL RESULTS")
        print('='*60)
        
        merged = merge_excel_extractions(all_results)
        print(f"\nMerged Success: {merged['success']}")
        print(f"Files Processed: {merged['files_processed']}")
        print(f"\n=== MERGED SUMMARY ===")
        print(f"Estrutura Metálica: {merged['summary']['estrutura_metalica_kg']:,.2f} kg")
        print(f"OMEGA: {merged['summary']['omega_kg']:,.2f} kg")
        print(f"Madres Galvanizadas: {merged['summary']['madres_galvanizadas_kg']:,.2f} kg")
        print(f"TOTAL: {merged['summary']['total_geral_kg']:,.2f} kg")
        
        if merged['duplicate_warnings']:
            print(f"\n=== DUPLICATE WARNINGS ===")
            for w in merged['duplicate_warnings']:
                print(f"  {w['profile_type']}: {w['file1']} vs {w['file2']}")
                print(f"    Values: {w['value1']:.2f} vs {w['value2']:.2f} ({w['difference_pct']:.1f}% diff)")
        
        if merged['requires_user_validation']:
            print(f"\n⚠️  {merged['validation_message']}")
