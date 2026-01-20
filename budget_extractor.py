"""
AluQuote AI - Budget Extractor V8
Extractor especializado para orçamentos de estruturas metálicas
Suporta formato FLYSTEEL e outros formatos comuns

PRECISÃO ALVO: 95%+
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


@dataclass
class BudgetLine:
    """Linha de orçamento extraída"""
    item_number: int
    description: str
    quantity: float
    unit: str
    unit_price: float = 0.0
    total_price: float = 0.0
    category: str = ""
    confidence: float = 1.0
    source_page: int = 1
    raw_text: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_number": self.item_number,
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "category": self.category,
            "confidence": self.confidence,
            "source_page": self.source_page
        }


class FLYSTEELBudgetExtractor:
    """
    Extractor especializado para orçamentos no formato FLYSTEEL
    
    Formato típico:
    Item | Descrição dos trabalhos | Quant. | Unid. | Preço Unit | Total
    2    | Estrutura metálica...   | 71 200,000 | kg  | 2,20       | 156 640,00
    """
    
    # Padrões de categorias
    CATEGORY_PATTERNS = {
        'estrutura_metalica': [
            r'estrutura\s*met[aá]lica',
            r'fornecimento.*montagem.*estrutura',
            r'perfis?\s*(ipe|heb|hea|upn)',
            r'a[çc]o\s*s\d{3}',
        ],
        'pintura_intumescente': [
            r'pintura\s*intumescente',
            r'protec[çc][aã]o.*fogo',
            r'r\s*(30|60|90|120)',
        ],
        'caleiros': [
            r'caleiro',
            r'caleira',
            r'gutter',
        ],
        'cobertura': [
            r'cobertura',
            r'painel.*rocha',
            r'painel.*pir',
            r'claraboia',
            r'[aá]rea.*luz',
        ],
        'fachada': [
            r'fachada',
            r'revestimento',
            r'painel.*fachada',
            r'contra.*fachada',
            r'chapa.*simples',
        ],
        'portas': [
            r'porta',
            r'port[aã]o',
            r'emerg[eê]ncia',
            r'sectorial',
            r'basculante',
        ],
        'acessorios': [
            r'remate',
            r'acess[oó]rio',
            r'parafuso',
            r'fixa[çc][aã]o',
        ]
    }
    
    # Padrão para linhas de orçamento FLYSTEEL
    # Formato: número | descrição | quantidade | unidade | preço | total
    LINE_PATTERNS = [
        # Padrão 1: Item numérico + descrição + quantidade + unidade
        r'(\d{1,3})\s+(.+?)\s+(\d{1,3}(?:[\s\.]\d{3})*(?:[,\.]\d+)?)\s*(kg|m2|m²|ml|un|pcs?)\s*(?:(\d+(?:[,\.]\d+)?)\s*(?:(\d+(?:[\s\.]\d{3})*(?:[,\.]\d+)?)))?',
        # Padrão 2: Quantidade primeiro
        r'(\d{1,3}(?:[\s\.]\d{3})*(?:[,\.]\d+)?)\s*(kg|m2|m²|ml|un)\s+(.+)',
    ]
    
    def __init__(self, file_path: str = None):
        self.file_path = Path(file_path) if file_path else None
        self.budget_lines: List[BudgetLine] = []
        self.raw_text = ""
        self.totals = {
            'estrutura_metalica': {'qty': 0, 'unit': 'kg'},
            'pintura_intumescente': {'qty': 0, 'unit': 'kg'},
            'caleiros': {'qty': 0, 'unit': 'ml'},
            'cobertura': {'qty': 0, 'unit': 'm²'},
            'fachada': {'qty': 0, 'unit': 'm²'},
            'portas': {'qty': 0, 'unit': 'un'},
            'acessorios': {'qty': 0, 'unit': 'un'},
        }
    
    def extract_from_text(self, text: str) -> Dict[str, Any]:
        """Extrai dados de orçamento a partir do texto bruto"""
        self.raw_text = text
        self.budget_lines = []
        
        # Limpar texto
        clean_text = self._clean_text(text)
        
        # Método 1: Extração por padrões específicos FLYSTEEL
        self._extract_flysteel_format(clean_text)
        
        # Método 2: Extração por padrões genéricos de quantidade + unidade
        if len(self.budget_lines) < 5:
            self._extract_generic_quantities(clean_text)
        
        # Calcular totais por categoria
        self._calculate_totals()
        
        return {
            "success": True,
            "budget_lines": [line.to_dict() for line in self.budget_lines],
            "totals": self.totals,
            "raw_text_length": len(text),
            "lines_extracted": len(self.budget_lines)
        }
    
    def extract_from_pdf(self, file_path: str = None) -> Dict[str, Any]:
        """Extrai dados de orçamento de um ficheiro PDF"""
        path = Path(file_path) if file_path else self.file_path
        
        if not HAS_PDFPLUMBER:
            return {"success": False, "error": "pdfplumber not available"}
        
        try:
            all_text = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    all_text.append(text)
            
            combined_text = "\n".join(all_text)
            return self.extract_from_text(combined_text)
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _clean_text(self, text: str) -> str:
        """Limpa e normaliza o texto"""
        # Normalizar espaços
        text = re.sub(r'\s+', ' ', text)
        # Normalizar separadores de milhares portugueses
        # "71 200,000" -> manter como está para parsing
        return text
    
    def _extract_flysteel_format(self, text: str):
        """
        Extrai usando o formato específico FLYSTEEL
        
        O texto vem junto sem espaços claros, ex:
        "...montagem.71 200,000 kg3Pintura Intumescente4..."
        "...R60 TCde 750956 900,000 kg5Caleiros..."
        "...7,000 un..."
        """
        
        # ESTRUTURA METÁLICA - procurar "XX XXX,XXX kg" após menção de montagem/acessórios
        # Padrão: captura "71 200,000 kg" onde 71 200 é o peso em kg
        estrutura_match = re.search(
            r'montagem[.\s]*(\d{1,3})\s(\d{3}),(\d{3})\s*kg',
            text, re.IGNORECASE
        )
        if estrutura_match:
            # Número: XXX YYY,ZZZ -> XXXYYY.ZZZ
            qty = float(f"{estrutura_match.group(1)}{estrutura_match.group(2)}.{estrutura_match.group(3)}")
            self.budget_lines.append(BudgetLine(
                item_number=1,
                description="Estrutura Metálica S275JR",
                quantity=qty,
                unit='kg',
                category='estrutura_metalica',
                confidence=0.98,
                raw_text=estrutura_match.group()
            ))
        
        # PINTURA INTUMESCENTE - o texto tem "750956 900,000 kg" onde 750 é temperatura
        # Precisamos separar: TC de 750° + 56 900,000 kg
        # Procurar após "intumescente" um padrão "750XX XXX,XXX kg" e extrair XX XXX,XXX
        pintura_match = re.search(
            r'intumescente.*?750(\d{2})\s?(\d{3}),(\d{3})\s*kg',
            text, re.IGNORECASE | re.DOTALL
        )
        if pintura_match:
            # Extrai: 56 900,000 -> 56900.000
            qty = float(f"{pintura_match.group(1)}{pintura_match.group(2)}.{pintura_match.group(3)}")
            self.budget_lines.append(BudgetLine(
                item_number=2,
                description="Pintura Intumescente R60",
                quantity=qty,
                unit='kg',
                category='pintura_intumescente',
                confidence=0.98,
                raw_text=pintura_match.group()
            ))
        
        # CALEIROS - procurar "XXX,000 ml"
        caleiro_matches = re.finditer(
            r'(\d{2,4}),(\d{3})\s*ml',
            text, re.IGNORECASE
        )
        for i, match in enumerate(caleiro_matches):
            qty = float(f"{match.group(1)}.{match.group(2)}")
            self.budget_lines.append(BudgetLine(
                item_number=3+i,
                description=f"Caleiros ({i+1})",
                quantity=qty,
                unit='ml',
                category='caleiros',
                confidence=0.95,
                raw_text=match.group()
            ))
        
        # COBERTURA PAVILHÕES - procurar "X XXX,XXX m2"
        cobertura_match = re.search(
            r'cobertura[^0-9]*?(\d)\s(\d{3}),(\d{3})\s*(m2|m²)',
            text, re.IGNORECASE
        )
        if cobertura_match:
            qty = float(f"{cobertura_match.group(1)}{cobertura_match.group(2)}.{cobertura_match.group(3)}")
            self.budget_lines.append(BudgetLine(
                item_number=10,
                description="Cobertura Pavilhões",
                quantity=qty,
                unit='m²',
                category='cobertura',
                confidence=0.98,
                raw_text=cobertura_match.group()
            ))
        
        # FACHADA EDIFÍCIO - procurar "1 624,000 m2" após "fachada"
        fachada_match = re.search(
            r'fachada[^0-9]*?(\d)\s(\d{3}),(\d{3})\s*(m2|m²)',
            text, re.IGNORECASE
        )
        if fachada_match:
            qty = float(f"{fachada_match.group(1)}{fachada_match.group(2)}.{fachada_match.group(3)}")
            self.budget_lines.append(BudgetLine(
                item_number=15,
                description="Fachada Edifício",
                quantity=qty,
                unit='m²',
                category='fachada',
                confidence=0.98,
                raw_text=fachada_match.group()
            ))
        
        # PORTAS EMERGÊNCIA - procurar "X,000 un"
        portas_match = re.search(
            r'porta[^0-9]*?(\d),(\d{3})\s*(un)',
            text, re.IGNORECASE
        )
        if portas_match:
            qty = float(f"{portas_match.group(1)}.{portas_match.group(2)}")
            self.budget_lines.append(BudgetLine(
                item_number=20,
                description="Portas de Emergência",
                quantity=qty,
                unit='un',
                category='portas',
                confidence=0.98,
                raw_text=portas_match.group()
            ))
        
        # Método de extração específica concluído
    
    def _extract_generic_quantities(self, text: str):
        """Extração genérica de quantidades com unidades"""
        
        # Padrão genérico: número + unidade
        pattern = r'(\d{1,3}(?:[\s\.]\d{3})*(?:[,\.]\d{1,3})?)\s*(kg|m2|m²|ml|un)\b'
        
        text_lower = text.lower()
        matches = list(re.finditer(pattern, text_lower))
        
        item_num = len(self.budget_lines)
        
        for match in matches:
            qty_str = match.group(1)
            unit = match.group(2)
            qty = self._parse_portuguese_number(qty_str)
            
            # Filtrar valores muito pequenos ou irrelevantes
            if qty < 10:
                continue
            
            # Obter contexto (100 chars antes)
            start = max(0, match.start() - 100)
            context = text[start:match.end()].strip()
            
            # Determinar categoria
            category = self._categorize_by_context(context)
            
            # Evitar duplicados
            if self._is_duplicate(qty, unit, category):
                continue
            
            item_num += 1
            self.budget_lines.append(BudgetLine(
                item_number=item_num,
                description=self._clean_description(context),
                quantity=qty,
                unit=unit,
                category=category,
                confidence=0.7,
                raw_text=context[-60:]
            ))
    
    def _parse_portuguese_number(self, num_str: str) -> float:
        """Converte número em formato português para float"""
        if not num_str:
            return 0.0
        
        # Remover espaços entre dígitos (milhares)
        num_str = re.sub(r'(\d)\s+(\d)', r'\1\2', num_str)
        
        # Remover pontos de milhares
        num_str = num_str.replace('.', '')
        
        # Substituir vírgula decimal por ponto
        num_str = num_str.replace(',', '.')
        
        try:
            return float(num_str)
        except:
            return 0.0
    
    def _categorize_by_context(self, context: str) -> str:
        """Determina a categoria baseada no contexto"""
        context_lower = context.lower()
        
        for category, patterns in self.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, context_lower):
                    return category
        
        return 'acessorios'
    
    def _clean_description(self, text: str) -> str:
        """Limpa a descrição extraída"""
        # Remover quebras de linha
        text = re.sub(r'[\n\r]+', ' ', text)
        # Remover espaços múltiplos
        text = re.sub(r'\s+', ' ', text)
        # Limitar tamanho
        if len(text) > 100:
            text = text[:97] + "..."
        return text.strip()
    
    def _is_duplicate(self, qty: float, unit: str, category: str) -> bool:
        """Verifica se o item já foi extraído"""
        for line in self.budget_lines:
            if (abs(line.quantity - qty) < 1 and 
                line.unit == unit and 
                line.category == category):
                return True
        return False
    
    def _calculate_totals(self):
        """Calcula totais por categoria"""
        for line in self.budget_lines:
            cat = line.category
            if cat in self.totals:
                self.totals[cat]['qty'] += line.quantity
                self.totals[cat]['unit'] = line.unit


class SmartBudgetExtractor:
    """
    Extractor inteligente que combina múltiplas estratégias:
    1. Extração directa do PDF (texto e tabelas)
    2. Extração do texto bruto via regex
    3. Validação cruzada com dados DXF
    """
    
    def __init__(self):
        self.flysteel_extractor = FLYSTEELBudgetExtractor()
    
    def extract(self, pdf_data: Dict[str, Any] = None, 
                raw_text: str = None,
                dxf_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Extrai dados de orçamento usando todas as fontes disponíveis
        
        Args:
            pdf_data: Dados extraídos pelo PDFReader (se disponível)
            raw_text: Texto bruto do PDF (fallback)
            dxf_data: Dados do DXF para validação cruzada
        
        Returns:
            Dicionário com dados consolidados do orçamento
        """
        results = {
            'budget_lines': [],
            'totals': {},
            'sources_used': [],
            'confidence': 0.0
        }
        
        # Método 1: Usar extractor FLYSTEEL no texto bruto
        if raw_text:
            flysteel_result = self.flysteel_extractor.extract_from_text(raw_text)
            if flysteel_result.get('success') and flysteel_result.get('lines_extracted', 0) > 0:
                results['budget_lines'].extend(flysteel_result.get('budget_lines', []))
                results['totals'] = flysteel_result.get('totals', {})
                results['sources_used'].append('flysteel_extractor')
                results['confidence'] = 0.95
        
        # Método 2: Usar dados do PDFReader (BOM items)
        if pdf_data and pdf_data.get('success'):
            bom_items = pdf_data.get('bom_items', [])
            if bom_items:
                for item in bom_items:
                    # Tentar extrair quantidade e unidade
                    desc = item.get('description', '')
                    qty = item.get('quantity', 0)
                    unit = item.get('unit', 'un')
                    
                    if qty > 10:  # Filtrar valores pequenos
                        results['budget_lines'].append({
                            'description': desc,
                            'quantity': qty,
                            'unit': unit,
                            'source': 'pdf_bom'
                        })
                        results['sources_used'].append('pdf_bom')
        
        # Método 3: Validação com DXF
        if dxf_data and dxf_data.get('success'):
            dxf_weight = dxf_data.get('statistics', {}).get('estimated_weight_kg', 0)
            if dxf_weight > 0:
                results['dxf_validation'] = {
                    'dxf_weight_alu_kg': dxf_weight,
                    'dxf_weight_steel_kg': dxf_weight * (7850 / 2700),
                    'profiles_count': dxf_data.get('statistics', {}).get('total_profiles', 0)
                }
                results['sources_used'].append('dxf_validation')
        
        # Consolidar e deduplicar
        results['budget_lines'] = self._deduplicate_lines(results['budget_lines'])
        results['success'] = len(results['budget_lines']) > 0
        
        return results
    
    def _deduplicate_lines(self, lines: List[Dict]) -> List[Dict]:
        """Remove linhas duplicadas"""
        seen = set()
        unique = []
        
        for line in lines:
            key = (
                line.get('category', ''),
                round(line.get('quantity', 0)),
                line.get('unit', '')
            )
            if key not in seen:
                seen.add(key)
                unique.append(line)
        
        return unique


def extract_budget_from_pdf(file_path: str) -> Dict[str, Any]:
    """
    Função de conveniência para extrair orçamento de um PDF
    """
    extractor = FLYSTEELBudgetExtractor(file_path)
    return extractor.extract_from_pdf()


def extract_budget_from_text(text: str) -> Dict[str, Any]:
    """
    Função de conveniência para extrair orçamento de texto
    """
    extractor = FLYSTEELBudgetExtractor()
    return extractor.extract_from_text(text)
