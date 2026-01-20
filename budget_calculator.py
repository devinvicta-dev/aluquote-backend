"""
AluQuote AI - Budget Calculator Module - V7 ENHANCED
Suporta múltiplos materiais (Aço, Alumínio, Inox)
Comparação inteligente DXF vs PDF com lógica de engenharia
Multiplicador de unidades para estruturas repetidas

ESTRUTURA DO ORÇAMENTO:
1. Estrutura Metálica (kg)
2. Pintura Intumescente (kg ou m²)
3. Caleiros (ml)
4. Cobertura (m²)
5. Fachada (m²)
6. Portas/Portões (un)
7. Acessórios/Remates (ml/un)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import math
import re
from difflib import SequenceMatcher

# Import FLYSTEEL cost database
try:
    from cost_database import cost_db, CostDatabase, SteelProfile, CladdingItem
    HAS_COST_DB = True
except ImportError:
    HAS_COST_DB = False
    cost_db = None


# ============== MATERIAL DEFINITIONS ==============
@dataclass
class MaterialSpec:
    """Material specification with physical properties"""
    code: str
    name: str
    density_kg_m3: float
    yield_strength_mpa: float = 0
    base_price_eur_kg: float = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "density_kg_m3": self.density_kg_m3,
            "yield_strength_mpa": self.yield_strength_mpa,
            "base_price_eur_kg": self.base_price_eur_kg
        }


class MaterialDatabase:
    """Database of common construction materials"""
    
    MATERIALS = {
        # Steel
        "S235": MaterialSpec("S235", "Aço S235JR", 7850, 235, 0.85),
        "S275": MaterialSpec("S275", "Aço S275JR", 7850, 275, 0.90),
        "S355": MaterialSpec("S355", "Aço S355JR", 7850, 355, 0.95),
        
        # Stainless Steel
        "INOX304": MaterialSpec("INOX304", "Aço Inox 304", 7930, 215, 3.50),
        "INOX316": MaterialSpec("INOX316", "Aço Inox 316", 8000, 205, 4.20),
        
        # Aluminum
        "AL6060": MaterialSpec("AL6060", "Alumínio 6060-T6", 2700, 150, 3.20),
        "AL6063": MaterialSpec("AL6063", "Alumínio 6063-T5", 2700, 130, 3.00),
        "AL6082": MaterialSpec("AL6082", "Alumínio 6082-T6", 2700, 250, 3.50),
        
        # Galvanized Steel
        "GALV": MaterialSpec("GALV", "Aço Galvanizado", 7850, 250, 1.10),
    }
    
    @classmethod
    def get_material(cls, code: str) -> Optional[MaterialSpec]:
        """Get material by code (case-insensitive, partial match)"""
        code_upper = code.upper().replace("-", "").replace("_", "").replace(" ", "")
        
        # Direct match
        if code_upper in cls.MATERIALS:
            return cls.MATERIALS[code_upper]
        
        # Partial match
        for key, mat in cls.MATERIALS.items():
            if code_upper in key or key in code_upper:
                return mat
            if code_upper in mat.name.upper().replace(" ", ""):
                return mat
        
        # Default to S275 steel
        return cls.MATERIALS.get("S275")
    
    @classmethod
    def detect_from_text(cls, text: str) -> Optional[MaterialSpec]:
        """Detect material from text description"""
        text_upper = text.upper()
        
        patterns = {
            "S275": [r"S\s*275", r"AÇO\s*275", r"STEEL\s*275"],
            "S355": [r"S\s*355", r"AÇO\s*355", r"STEEL\s*355"],
            "S235": [r"S\s*235", r"AÇO\s*235", r"STEEL\s*235"],
            "INOX304": [r"INOX\s*304", r"304\s*L?", r"STAINLESS"],
            "INOX316": [r"INOX\s*316", r"316\s*L?"],
            "AL6063": [r"60\s*63", r"ALUMÍ?NIO.*60\s*63", r"EN\s*AW.*60\s*63"],
            "AL6060": [r"60\s*60", r"ALUMÍ?NIO.*60\s*60"],
            "AL6082": [r"60\s*82", r"ALUMÍ?NIO.*60\s*82"],
            "GALV": [r"GALVANIZ", r"ZINCO", r"HDG"],
        }
        
        for code, pats in patterns.items():
            for pat in pats:
                if re.search(pat, text_upper):
                    return cls.MATERIALS.get(code)
        
        return None
    
    @classmethod
    def get_all(cls) -> List[MaterialSpec]:
        return list(cls.MATERIALS.values())


# ============== CATEGORIAS DE ORÇAMENTO ==============
class BudgetCategory:
    """Categorias do orçamento no estilo FLYSTEEL"""
    ESTRUTURA_METALICA = "estrutura_metalica"
    MADRES = "madres"  # Madres galvanizadas (cobertura/fachada)
    PINTURA_INTUMESCENTE = "pintura_intumescente"
    CALEIROS = "caleiros"
    COBERTURA = "cobertura"
    FACHADA = "fachada"
    PORTAS = "portas"
    ACESSORIOS = "acessorios"
    REVESTIMENTOS = "revestimentos"  # Generic cladding category
    
    @staticmethod
    def get_display_name(category: str) -> str:
        names = {
            "estrutura_metalica": "Estrutura Metálica",
            "madres": "Madres Galvanizadas",
            "pintura_intumescente": "Pintura Intumescente",
            "caleiros": "Caleiros",
            "cobertura": "Cobertura",
            "fachada": "Fachada",
            "portas": "Portas e Portões",
            "acessorios": "Acessórios e Remates",
            "revestimentos": "Revestimentos"
        }
        return names.get(category, category.replace("_", " ").title())
    
    @staticmethod
    def get_order(category: str) -> int:
        order = {
            "estrutura_metalica": 1,
            "madres": 2,
            "pintura_intumescente": 3,
            "caleiros": 4,
            "cobertura": 5,
            "fachada": 6,
            "portas": 7,
            "acessorios": 8,
            "revestimentos": 9
        }
        return order.get(category, 99)


@dataclass
class PricingParameters:
    """Global pricing parameters"""
    lme_price_usd_kg: float = 2.35
    lme_hedging_buffer_pct: float = 5.0
    billet_premium_usd_kg: float = 0.45
    alloy_6063_premium_pct: float = 0.0
    alloy_6060_premium_pct: float = 2.0
    alloy_6082_premium_pct: float = 8.0
    anodizing_natural_eur_m2: float = 12.0
    anodizing_colored_eur_m2: float = 18.0
    powder_coating_standard_eur_m2: float = 15.0
    powder_coating_qualicoat_eur_m2: float = 22.0
    powder_coating_seaside_eur_m2: float = 35.0
    labor_rate_eur_hr: float = 35.0
    cutting_time_mins: float = 2.0
    machining_time_per_hole_mins: float = 5.0
    assembly_time_per_component_mins: float = 8.0
    base_waste_factor_pct: float = 8.0
    complexity_waste_factor_pct: float = 4.0
    overhead_factor_pct: float = 15.0
    profit_margin_pct: float = 20.0
    eur_to_usd: float = 1.08
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "lme_price_usd_kg": self.lme_price_usd_kg,
            "lme_hedging_buffer_pct": self.lme_hedging_buffer_pct,
            "billet_premium_usd_kg": self.billet_premium_usd_kg,
            "surface_treatments": {
                "anodizing_natural": self.anodizing_natural_eur_m2,
                "anodizing_colored": self.anodizing_colored_eur_m2,
                "powder_coating_standard": self.powder_coating_standard_eur_m2,
                "powder_coating_qualicoat": self.powder_coating_qualicoat_eur_m2,
                "powder_coating_seaside": self.powder_coating_seaside_eur_m2
            },
            "labor_rate_eur_hr": self.labor_rate_eur_hr,
            "waste_factor_pct": self.base_waste_factor_pct,
            "overhead_factor_pct": self.overhead_factor_pct,
            "profit_margin_pct": self.profit_margin_pct
        }


@dataclass
class BudgetLineItem:
    """Single line item in the budget - FLYSTEEL style"""
    item_number: int
    category: str
    description: str
    quantity: float
    unit: str  # kg, ml, m², un
    unit_price: float
    total_price: float
    
    # Detailed breakdown
    material_spec: str = ""
    material_code: str = ""
    weight_kg: float = 0.0
    area_m2: float = 0.0
    length_ml: float = 0.0
    
    # Source and confidence
    source: str = ""  # dxf, pdf, reconciled, estimated
    confidence: float = 0.0
    notes: str = ""
    
    # Reconciliation info
    dxf_value: float = 0.0
    pdf_value: float = 0.0
    reconciliation_method: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_number": self.item_number,
            "category": self.category,
            "category_name": BudgetCategory.get_display_name(self.category),
            "description": self.description,
            "quantity": round(self.quantity, 3),
            "unit": self.unit,
            "unit_price": round(self.unit_price, 2),
            "total_price": round(self.total_price, 2),
            "material_spec": self.material_spec,
            "material_code": self.material_code,
            "details": {
                "weight_kg": round(self.weight_kg, 2),
                "area_m2": round(self.area_m2, 2),
                "length_ml": round(self.length_ml, 2)
            },
            "source": self.source,
            "confidence": round(self.confidence, 2),
            "notes": self.notes,
            "reconciliation": {
                "dxf_value": round(self.dxf_value, 2) if self.dxf_value else None,
                "pdf_value": round(self.pdf_value, 2) if self.pdf_value else None,
                "method": self.reconciliation_method
            }
        }


@dataclass 
class BudgetSection:
    """Section of the budget (grouped items by category)"""
    category: str
    category_name: str
    items: List[BudgetLineItem] = field(default_factory=list)
    subtotal: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "category_name": self.category_name,
            "items": [item.to_dict() for item in self.items],
            "subtotal": round(self.subtotal, 2),
            "item_count": len(self.items)
        }


@dataclass
class BudgetTerms:
    """Terms and conditions for the budget"""
    prazo_obra: str = "A combinar"
    condicoes_pagamento: str = "30% na adjudicação. Restante por autos mensais a 30 dias"
    validade_dias: int = 30
    nao_inclui: List[str] = field(default_factory=lambda: [
        "Trabalhos de construção civil",
        "Fornecimento de energia elétrica",
        "Licenças",
        "Outros que não os mencionados neste orçamento"
    ])
    notas: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prazo_obra": self.prazo_obra,
            "condicoes_pagamento": self.condicoes_pagamento,
            "validade_dias": self.validade_dias,
            "nao_inclui": self.nao_inclui,
            "notas": self.notas
        }


@dataclass
class ReconciliationResult:
    """Result of DXF vs PDF reconciliation"""
    category: str
    dxf_value: float
    pdf_value: float
    reconciled_value: float
    unit: str
    confidence: float
    method: str  # "dxf_priority", "pdf_priority", "average", "engineering_calc", "multiplier"
    explanation: str
    multiplier_used: float = 1.0


@dataclass
class BudgetSummary:
    """Complete budget summary - FLYSTEEL style"""
    project_name: str
    project_reference: str
    created_at: str
    client_name: str = ""
    client_attention: str = ""
    
    # Material info
    primary_material: str = "S275"
    material_name: str = "Aço S275JR"
    
    # Unit multiplier
    unit_multiplier: int = 1
    unit_description: str = ""  # e.g., "3 pavilhões"
    
    # Source info
    has_dxf: bool = False
    has_pdf: bool = False
    
    # Reconciliation stats
    reconciliation_results: List[ReconciliationResult] = field(default_factory=list)
    
    # Sections
    sections: List[BudgetSection] = field(default_factory=list)
    
    # Totals
    subtotal: float = 0.0
    iva_rate: float = 23.0
    iva_value: float = 0.0
    total_com_iva: float = 0.0
    
    # Terms
    terms: BudgetTerms = field(default_factory=BudgetTerms)
    
    # Metrics
    total_weight_kg: float = 0.0
    total_area_m2: float = 0.0
    total_length_ml: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "project_reference": self.project_reference,
            "created_at": self.created_at,
            "client_name": self.client_name,
            "client_attention": self.client_attention,
            "material": {
                "code": self.primary_material,
                "name": self.material_name
            },
            "multiplier": {
                "value": self.unit_multiplier,
                "description": self.unit_description
            },
            "sources": {
                "has_dxf": self.has_dxf,
                "has_pdf": self.has_pdf
            },
            "reconciliation": [
                {
                    "category": r.category,
                    "dxf_value": r.dxf_value,
                    "pdf_value": r.pdf_value,
                    "reconciled_value": r.reconciled_value,
                    "unit": r.unit,
                    "confidence": r.confidence,
                    "method": r.method,
                    "explanation": r.explanation
                }
                for r in self.reconciliation_results
            ],
            "sections": [s.to_dict() for s in self.sections],
            "totals": {
                "subtotal": round(self.subtotal, 2),
                "iva_rate": self.iva_rate,
                "iva_value": round(self.iva_value, 2),
                "total_com_iva": round(self.total_com_iva, 2)
            },
            "terms": self.terms.to_dict(),
            "metrics": {
                "total_weight_kg": round(self.total_weight_kg, 2),
                "total_area_m2": round(self.total_area_m2, 2),
                "total_length_ml": round(self.total_length_ml, 2)
            }
        }


class ItemCategorizer:
    """Categoriza itens automaticamente baseado em descrição/layer"""
    
    PATTERNS = {
        BudgetCategory.ESTRUTURA_METALICA: [
            r'estrutura', r'metalica', r'metal', r'aco', r'aço', r's275', r's355',
            r'ipe\s*\d+', r'heb\s*\d+', r'hea\s*\d+', r'upn\s*\d+',
            r'rhs', r'shs', r'tubo', r'pilar', r'viga', r'madre',
            r'trelic', r'asna', r'travessa', r'contravent', r'diagonal',
            r'perfil', r'barra', r'cantoneira', r'chapa.*preta',
            # Layer patterns for DXF
            r'est[_\-]?\d+', r'str[_\-]?\d+', r'steel', r'frame',
            r'pil[_\-]?\d+', r'vig[_\-]?\d+', r'mad[_\-]?\d+'
        ],
        BudgetCategory.PINTURA_INTUMESCENTE: [
            r'intumescente', r'r30', r'r60', r'r90', r'protec.*fogo',
            r'pintura.*estrutur', r'revestimento.*fogo'
        ],
        BudgetCategory.CALEIROS: [
            r'caleira', r'caleiro', r'gutter', r'drenagem', r'escoamento'
        ],
        BudgetCategory.COBERTURA: [
            r'cobertura', r'telhado', r'painel.*rocha', r'painel.*pir',
            r'painel.*poliuret', r'chapa.*cobert', r'claraboia',
            r'area.*luz', r'anticume', r'cume', r'rufos', r'cobert'
        ],
        BudgetCategory.FACHADA: [
            r'fachada', r'revestimento', r'painel.*fachada', r'chapa.*simples',
            r'prelacada', r'alucobond', r'contra.*fachada', r'forra'
        ],
        BudgetCategory.PORTAS: [
            r'porta', r'portao', r'portão', r'emergencia', r'emergência',
            r'sectorial', r'basculante', r'correr', r'janela', r'caixilh'
        ],
        BudgetCategory.ACESSORIOS: [
            r'remate', r'acessorio', r'parafuso', r'fixac', r'vedante',
            r'isolamento', r'selante', r'apoio', r'suporte', r'bracket'
        ]
    }
    
    @classmethod
    def categorize(cls, description: str, layer: str = "") -> str:
        """Categoriza um item baseado na descrição e layer"""
        text = f"{description} {layer}".lower()
        
        for category, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return category
        
        # Default to estrutura for uncategorized steel profiles or EST_ layers
        if re.search(r'(ipe|heb|hea|upn|rhs|shs|tubo|est[_\-]\d+|str[_\-])', text):
            return BudgetCategory.ESTRUTURA_METALICA
        
        # If layer starts with common structure prefixes, treat as structure
        layer_lower = layer.lower()
        if layer_lower.startswith(('est', 'str', 'pil', 'vig', 'mad', 'frame')):
            return BudgetCategory.ESTRUTURA_METALICA
        
        return BudgetCategory.ACESSORIOS
    
    @classmethod
    def get_unit(cls, category: str, description: str = "") -> str:
        """Retorna a unidade apropriada para a categoria"""
        desc_lower = description.lower()
        
        if category == BudgetCategory.ESTRUTURA_METALICA:
            return "kg"
        elif category == BudgetCategory.PINTURA_INTUMESCENTE:
            if "m2" in desc_lower or "área" in desc_lower or "area" in desc_lower:
                return "m²"
            return "kg"
        elif category == BudgetCategory.CALEIROS:
            return "ml"
        elif category == BudgetCategory.COBERTURA:
            if "claraboia" in desc_lower:
                return "un"
            return "m²"
        elif category == BudgetCategory.FACHADA:
            if "remate" in desc_lower:
                return "ml"
            return "m²"
        elif category == BudgetCategory.PORTAS:
            return "un"
        elif category == BudgetCategory.ACESSORIOS:
            if "remate" in desc_lower:
                return "ml"
            return "un"
        return "un"


class DescriptionGenerator:
    """Gera descrições profissionais no estilo FLYSTEEL"""
    
    @staticmethod
    def generate_structure_description(profile_type: str, material: str = "S275JR",
                                       treatment: str = "pintura") -> str:
        desc = f"Fornecimento e montagem de estrutura metálica em aço {material}"
        
        if treatment == "pintura":
            desc += " incluindo esquema de tratamento decapagem ao Grau SA2 1/2, "
            desc += "uma demão de primário e uma demão de acabamento"
        elif treatment == "galvanizado":
            desc += " com tratamento de galvanização a quente"
        
        if profile_type:
            desc += f", incluindo perfis {profile_type}"
        
        desc += ", incluindo todas as chapas de ligação e todos os acessórios para uma boa montagem."
        return desc
    
    @staticmethod
    def generate_painting_description(fire_rating: str = "R60") -> str:
        return f"Serviço de aplicação de pintura intumescente {fire_rating}"
    
    @staticmethod
    def generate_gutter_description(gutter_type: str = "duplo") -> str:
        if gutter_type == "duplo":
            return ("Fornecimento e montagem de caleiros duplos constituídos por uma "
                   "forra em chapa prelacada, isolamento lã de rocha e uma caleira "
                   "interior em chapa galvanizada com pintura pelo exterior")
        else:
            return "Fornecimento e montagem de caleiros simples em chapa galvanizada de 1,5mm com pintura nas duas faces"
    
    @staticmethod
    def generate_roof_description(panel_type: str = "la_rocha", thickness: int = 50) -> str:
        if panel_type == "la_rocha":
            return (f"Fornecimento e montagem de painel de lã de rocha com {thickness}mm "
                   f"ref PC1000/{thickness}mm, incluindo as áreas de luz representadas no desenho "
                   "e todos os remates e acessórios para uma boa montagem")
        elif panel_type == "poliuretano":
            return (f"Fornecimento e montagem de cobertura em Painel PC3-1000 de {thickness}mm "
                   "de espessura em poliuretano BS2D0 com chapa exterior e interior, "
                   "incluindo todos os remates e acessórios para uma boa montagem.")
        return "Fornecimento e montagem de cobertura"
    
    @staticmethod
    def generate_facade_description(panel_type: str = "la_rocha", thickness: int = 50) -> str:
        if panel_type == "la_rocha":
            return (f"Fornecimento e montagem de fachada em painel lã de rocha de {thickness}mm "
                   f"Ref FTBPFO1000/{thickness}mm DS nas cores standard catálogo, "
                   "incluindo todos os remates e acessórios para uma boa montagem")
        elif panel_type == "poliuretano":
            return (f"Fornecimento e montagem de painel PIR Arcelormittal 1025MM "
                   "Micronervurado chapa 06 exterior 04 interior")
        elif panel_type == "chapa_simples":
            return ("Fornecimento e montagem de fachada em chapa simples, "
                   "incluindo remates e acessórios para uma boa montagem.")
        return "Fornecimento e montagem de fachada"
    
    @staticmethod
    def generate_door_description(door_type: str, dimensions: str = "900x2150") -> str:
        if door_type == "emergencia":
            return f"Fornecimento e montagem de portas de emergência incluindo barra antipânico de dimensão {dimensions}mm"
        elif door_type == "sectorial":
            return f"Fornecimento e montagem de porta sectorial motorizada de dimensão {dimensions}mm"
        elif door_type == "basculante":
            return f"Fornecimento e montagem de portão basculante de dimensão {dimensions}mm"
        return "Fornecimento e montagem de porta"


class DXFPDFReconciler:
    """
    Motor de Reconciliação DXF vs PDF
    
    Compara dados extraídos do DXF com especificações do PDF e usa
    lógica de engenharia para resolver discrepâncias.
    """
    
    # Típicos rácios de peso por área para diferentes estruturas
    WEIGHT_PER_AREA_RATIOS = {
        "pavilhao_industrial": 27.0,  # kg/m² de área de implantação
        "nave_industrial": 25.0,
        "armazem": 22.0,
        "coberto": 18.0,
        "estrutura_ligeira": 15.0,
    }
    
    # Típicos rácios de painéis
    CLADDING_COVERAGE = {
        "cobertura": 1.05,  # 5% extra para overlaps
        "fachada": 1.08,    # 8% extra para aberturas/remates
    }
    
    def __init__(self, material: MaterialSpec, unit_multiplier: int = 1):
        self.material = material
        self.unit_multiplier = unit_multiplier
        self.results: List[ReconciliationResult] = []
    
    def reconcile(self, dxf_data: Dict, pdf_data: Dict) -> List[ReconciliationResult]:
        """Main reconciliation method"""
        self.results = []
        
        # Extract aggregated data from both sources
        dxf_summary = self._summarize_dxf(dxf_data)
        pdf_summary = self._summarize_pdf(pdf_data)
        
        # Reconcile each category
        categories = set(list(dxf_summary.keys()) + list(pdf_summary.keys()))
        
        for category in categories:
            dxf_val = dxf_summary.get(category, {})
            pdf_val = pdf_summary.get(category, {})
            
            result = self._reconcile_category(category, dxf_val, pdf_val)
            if result:
                self.results.append(result)
        
        return self.results
    
    def _summarize_dxf(self, dxf_data: Dict) -> Dict[str, Dict]:
        """Summarize DXF data by category with material density conversion"""
        summary = {}
        
        if not dxf_data.get('success', False):
            return summary
        
        profiles = dxf_data.get('profiles', [])
        stats = dxf_data.get('statistics', {})
        
        # DXF parser uses aluminum density (2700 kg/m³) by default
        # Convert to target material density
        DXF_BASE_DENSITY = 2700.0  # Aluminum density used by DXF parser
        density_conversion = self.material.density_kg_m3 / DXF_BASE_DENSITY
        
        # Calculate total weight and categorize
        total_weight = stats.get('estimated_weight_kg', 0) * density_conversion
        total_length = stats.get('total_length_mm', 0) / 1000  # Convert to meters
        total_area = stats.get('total_area_mm2', 0) / 1e6  # Convert to m²
        
        # Categorize profiles by layer
        for profile in profiles:
            layer = profile.get('layer', '')
            category = ItemCategorizer.categorize('', layer)
            
            if category not in summary:
                summary[category] = {
                    'weight_kg': 0,
                    'length_m': 0,
                    'area_m2': 0,
                    'count': 0
                }
            
            # Apply density conversion to weight
            raw_weight = profile.get('weight_kg', 0) * profile.get('quantity', 1)
            summary[category]['weight_kg'] += raw_weight * density_conversion
            summary[category]['length_m'] += profile.get('length_mm', 0) / 1000 * profile.get('quantity', 1)
            summary[category]['area_m2'] += profile.get('area_mm2', 0) / 1e6 * profile.get('quantity', 1)
            summary[category]['count'] += profile.get('quantity', 1)
        
        # If no categorized weight, put all in estrutura
        if not summary and total_weight > 0:
            summary[BudgetCategory.ESTRUTURA_METALICA] = {
                'weight_kg': total_weight,
                'length_m': total_length,
                'area_m2': total_area,
                'count': len(profiles)
            }
        
        return summary
    
    def _summarize_pdf(self, pdf_data: Dict) -> Dict[str, Dict]:
        """Summarize PDF data by category"""
        summary = {}
        
        if not pdf_data.get('success', False):
            return summary
        
        bom_items = pdf_data.get('bom_items', [])
        
        for item in bom_items:
            desc = item.get('description', '')
            category = ItemCategorizer.categorize(desc)
            qty = float(item.get('quantity', 0))
            unit = item.get('unit', '').lower()
            
            if category not in summary:
                summary[category] = {
                    'weight_kg': 0,
                    'length_m': 0,
                    'area_m2': 0,
                    'count': 0,
                    'items': []
                }
            
            # Parse quantity based on unit
            if 'kg' in unit:
                summary[category]['weight_kg'] += qty
            elif 'ml' in unit or 'm' == unit:
                summary[category]['length_m'] += qty
            elif 'm2' in unit or 'm²' in unit:
                summary[category]['area_m2'] += qty
            elif 'un' in unit:
                summary[category]['count'] += int(qty)
            
            summary[category]['items'].append(item)
        
        return summary
    
    def _reconcile_category(self, category: str, dxf_val: Dict, pdf_val: Dict) -> Optional[ReconciliationResult]:
        """Reconcile a single category using engineering logic"""
        
        # Determine primary unit for this category
        unit = ItemCategorizer.get_unit(category)
        
        # Get values based on unit
        if unit == "kg":
            dxf_qty = dxf_val.get('weight_kg', 0)
            pdf_qty = pdf_val.get('weight_kg', 0)
        elif unit == "m²":
            dxf_qty = dxf_val.get('area_m2', 0)
            pdf_qty = pdf_val.get('area_m2', 0)
        elif unit == "ml":
            dxf_qty = dxf_val.get('length_m', 0)
            pdf_qty = pdf_val.get('length_m', 0)
        else:
            dxf_qty = dxf_val.get('count', 0)
            pdf_qty = pdf_val.get('count', 0)
        
        # Apply multiplier to DXF values (DXF may show only 1 unit)
        dxf_qty_adjusted = dxf_qty * self.unit_multiplier
        
        # Skip if both are zero
        if dxf_qty == 0 and pdf_qty == 0:
            return None
        
        # Determine reconciliation method
        if pdf_qty > 0 and dxf_qty_adjusted > 0:
            # Both sources have data - compare and reconcile
            ratio = pdf_qty / dxf_qty_adjusted if dxf_qty_adjusted > 0 else 0
            
            if 0.9 <= ratio <= 1.1:
                # Values match within 10% - use average
                reconciled = (pdf_qty + dxf_qty_adjusted) / 2
                method = "average"
                confidence = 0.95
                explanation = f"Valores DXF ({dxf_qty_adjusted:.2f}) e PDF ({pdf_qty:.2f}) coincidem (±10%)"
            elif ratio > 1.1:
                # PDF has more - PDF is likely correct (more detailed specification)
                reconciled = pdf_qty
                method = "pdf_priority"
                confidence = 0.85
                explanation = f"PDF ({pdf_qty:.2f}) > DXF×{self.unit_multiplier} ({dxf_qty_adjusted:.2f}). PDF inclui especificações adicionais."
            else:
                # DXF has more - engineering calculation needed
                reconciled = dxf_qty_adjusted
                method = "dxf_priority"
                confidence = 0.80
                explanation = f"DXF×{self.unit_multiplier} ({dxf_qty_adjusted:.2f}) > PDF ({pdf_qty:.2f}). Geometria DXF prevalece."
        elif pdf_qty > 0:
            # Only PDF has data
            reconciled = pdf_qty
            method = "pdf_only"
            confidence = 0.70
            explanation = f"Apenas PDF disponível ({pdf_qty:.2f})"
        else:
            # Only DXF has data
            reconciled = dxf_qty_adjusted
            method = "dxf_only"
            confidence = 0.75
            explanation = f"Apenas DXF disponível ({dxf_qty:.2f}) × multiplicador {self.unit_multiplier}"
        
        return ReconciliationResult(
            category=category,
            dxf_value=dxf_qty,
            pdf_value=pdf_qty,
            reconciled_value=reconciled,
            unit=unit,
            confidence=confidence,
            method=method,
            explanation=explanation,
            multiplier_used=self.unit_multiplier
        )
    
    def detect_multiplier(self, dxf_data: Dict, pdf_data: Dict) -> int:
        """
        Detecta automaticamente o multiplicador necessário comparando DXF e PDF.
        Usa lógica de engenharia para determinar quantas unidades o PDF representa.
        """
        dxf_weight = dxf_data.get('statistics', {}).get('estimated_weight_kg', 0)
        
        # Try to find total weight in PDF
        pdf_weight = 0
        bom_items = pdf_data.get('bom_items', [])
        for item in bom_items:
            desc = item.get('description', '').lower()
            unit = item.get('unit', '').lower()
            qty = float(item.get('quantity', 0))
            
            if 'estrutura' in desc and 'kg' in unit:
                pdf_weight = qty
                break
        
        if dxf_weight > 0 and pdf_weight > 0:
            ratio = pdf_weight / dxf_weight
            # Round to nearest integer
            multiplier = max(1, round(ratio))
            
            # Sanity check - multiplier shouldn't be too high
            if multiplier <= 10:
                return multiplier
        
        return 1


class BudgetCalculator:
    """
    Budget Calculator - V7 Enhanced
    
    Suporta:
    - Múltiplos materiais (Aço, Alumínio, Inox)
    - Multiplicador de unidades
    - Comparação inteligente DXF vs PDF
    - Reconciliação com lógica de engenharia
    """
    
    def __init__(self, params: Optional[PricingParameters] = None):
        self.params = params or PricingParameters()
        self.items: List[BudgetLineItem] = []
        self.summary: Optional[BudgetSummary] = None
        self.material: MaterialSpec = MaterialDatabase.get_material("S275")
        self.unit_multiplier: int = 1
        
    def calculate_budget(self, dxf_data: Dict[str, Any], 
                        pdf_data: Dict[str, Any],
                        surface_treatment: str = "powder_coating_standard",
                        project_name: str = "Novo Orçamento",
                        client_name: str = "",
                        project_reference: str = "",
                        material_code: str = "S275",
                        unit_multiplier: int = 1,
                        auto_detect_multiplier: bool = True,
                        excel_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Main budget calculation method with reconciliation.
        PRIORITY: Excel FLYSTEEL > DXF > PDF
        Excel data provides 95%+ accuracy for steel quantities.
        """
        has_dxf = dxf_data.get('success', False) and len(dxf_data.get('profiles', [])) > 0
        has_pdf = pdf_data.get('success', False)
        has_excel = excel_data is not None and excel_data.get('success', False)
        
        # Set material
        self.material = MaterialDatabase.get_material(material_code) or MaterialDatabase.get_material("S275")
        
        # Auto-detect or use provided multiplier
        if auto_detect_multiplier and has_dxf and has_pdf:
            reconciler = DXFPDFReconciler(self.material, 1)
            detected = reconciler.detect_multiplier(dxf_data, pdf_data)
            self.unit_multiplier = max(unit_multiplier, detected)
        else:
            self.unit_multiplier = unit_multiplier
        
        # Reconcile DXF and PDF data
        reconciler = DXFPDFReconciler(self.material, self.unit_multiplier)
        reconciliation_results = []
        
        if has_dxf and has_pdf:
            reconciliation_results = reconciler.reconcile(dxf_data, pdf_data)
        
        # Reset items
        self.items = []
        item_number = 0
        
        # Generate project reference if not provided
        if not project_reference:
            project_reference = f"ORC-{datetime.now().strftime('%Y%m%d')}"
        
        # ============== GENERATE BUDGET ITEMS ==============
        
        # PRIORITY 1: Use Excel FLYSTEEL data (95%+ accuracy)
        if has_excel:
            item_number = self._process_excel_data(excel_data, surface_treatment, item_number)
        elif reconciliation_results:
            # Use reconciled data
            for result in reconciliation_results:
                item_number += 1
                unit_price = self._get_unit_price(result.category, result.unit, surface_treatment)
                
                self.items.append(BudgetLineItem(
                    item_number=item_number,
                    category=result.category,
                    description=self._generate_category_description_v2(result.category, surface_treatment),
                    quantity=result.reconciled_value,
                    unit=result.unit,
                    unit_price=unit_price,
                    total_price=result.reconciled_value * unit_price,
                    material_code=self.material.code,
                    material_spec=self.material.name,
                    weight_kg=result.reconciled_value if result.unit == "kg" else 0,
                    area_m2=result.reconciled_value if result.unit == "m²" else 0,
                    length_ml=result.reconciled_value if result.unit == "ml" else 0,
                    source="reconciled",
                    confidence=result.confidence,
                    dxf_value=result.dxf_value,
                    pdf_value=result.pdf_value,
                    reconciliation_method=result.method,
                    notes=result.explanation
                ))
        elif has_dxf:
            # Only DXF - process with multiplier
            item_number = self._process_dxf_only(dxf_data, surface_treatment, item_number)
        elif has_pdf:
            # Only PDF - process directly
            item_number = self._process_pdf_only(pdf_data, surface_treatment, item_number)
        
        # ============== GENERATE SUMMARY ==============
        self._generate_summary(
            project_name, project_reference, client_name, 
            has_dxf, has_pdf, reconciliation_results
        )
        
        return {
            "success": True,
            "summary": self.summary.to_dict() if self.summary else None,
            "line_items": [item.to_dict() for item in self.items],
            "parameters": self.params.to_dict(),
            "material": self.material.to_dict(),
            "unit_multiplier": self.unit_multiplier,
            "data_sources": {
                "dxf_used": has_dxf,
                "pdf_used": has_pdf,
                "reconciliation_performed": len(reconciliation_results) > 0
            }
        }
    
    def _process_dxf_only(self, dxf_data: Dict, treatment: str, start_num: int) -> int:
        """Process DXF data only, applying multiplier"""
        item_number = start_num
        profiles = dxf_data.get('profiles', [])
        
        # Group by category
        categorized = {}
        for profile in profiles:
            layer = profile.get('layer', '')
            category = ItemCategorizer.categorize('', layer)
            
            if category not in categorized:
                categorized[category] = {
                    'weight_kg': 0,
                    'length_m': 0,
                    'area_m2': 0,
                    'profiles': []
                }
            
            qty = profile.get('quantity', 1)
            categorized[category]['weight_kg'] += profile.get('weight_kg', 0) * qty
            categorized[category]['length_m'] += profile.get('length_mm', 0) / 1000 * qty
            categorized[category]['area_m2'] += profile.get('area_mm2', 0) / 1e6 * qty
            categorized[category]['profiles'].append(profile)
        
        for category, data in categorized.items():
            unit = ItemCategorizer.get_unit(category)
            
            if unit == "kg":
                quantity = data['weight_kg'] * self.unit_multiplier
            elif unit == "m²":
                quantity = data['area_m2'] * self.unit_multiplier
            elif unit == "ml":
                quantity = data['length_m'] * self.unit_multiplier
            else:
                quantity = len(data['profiles']) * self.unit_multiplier
            
            if quantity > 0:
                item_number += 1
                unit_price = self._get_unit_price(category, unit, treatment)
                
                self.items.append(BudgetLineItem(
                    item_number=item_number,
                    category=category,
                    description=self._generate_category_description_v2(category, treatment),
                    quantity=quantity,
                    unit=unit,
                    unit_price=unit_price,
                    total_price=quantity * unit_price,
                    material_code=self.material.code,
                    material_spec=self.material.name,
                    weight_kg=data['weight_kg'] * self.unit_multiplier,
                    source="dxf",
                    confidence=0.75,
                    notes=f"Multiplicador: {self.unit_multiplier}x"
                ))
        
        return item_number
    
    def _process_excel_data(self, excel_data: Dict, treatment: str, start_num: int) -> int:
        """
        Process FLYSTEEL Excel data (95%+ accuracy).
        Creates budget items from accurate Excel quantities.
        """
        item_number = start_num
        confidence = excel_data.get('confidence', 0.95)
        
        # Item 1: Estrutura Metálica Principal (non-galvanized steel)
        estrutura_kg = excel_data.get('estrutura_metalica_kg', 0)
        if estrutura_kg > 0:
            item_number += 1
            unit_price = self._get_unit_price(BudgetCategory.ESTRUTURA_METALICA, "kg", treatment)
            
            self.items.append(BudgetLineItem(
                item_number=item_number,
                category=BudgetCategory.ESTRUTURA_METALICA,
                description=f"Fornecimento e montagem de estrutura metálica em aço {self.material.name}, "
                           f"incluindo tratamento de decapagem SA 2½, primário e acabamento",
                quantity=round(estrutura_kg, 2),
                unit="kg",
                unit_price=unit_price,
                total_price=estrutura_kg * unit_price,
                material_code=self.material.code,
                material_spec=self.material.name,
                weight_kg=estrutura_kg,
                source="excel_flysteel",
                confidence=confidence,
                notes="Quantidade extraída de Excel FLYSTEEL (95%+ precisão)"
            ))
        
        # Item 2: Madres Galvanizadas (cobertura/fachada) - excluding OMEGA
        omega_kg = excel_data.get('omega_kg', 0)
        madres_kg = excel_data.get('madres_galvanizadas_kg', 0)
        # madres_galvanizadas_kg já inclui omega, então subtraímos para evitar duplicação
        madres_only_kg = madres_kg - omega_kg if madres_kg > omega_kg else 0
        
        if madres_only_kg > 0:
            item_number += 1
            unit_price = self._get_unit_price(BudgetCategory.MADRES, "kg", treatment)
            
            self.items.append(BudgetLineItem(
                item_number=item_number,
                category=BudgetCategory.MADRES,
                description="Fornecimento e montagem de madres de cobertura e fachada em chapa galvanizada",
                quantity=round(madres_only_kg, 2),
                unit="kg",
                unit_price=unit_price,
                total_price=madres_only_kg * unit_price,
                material_code="GALV",
                material_spec="Aço Galvanizado",
                weight_kg=madres_only_kg,
                source="excel_flysteel",
                confidence=confidence,
                notes="Madres galvanizadas - não requerem pintura intumescente"
            ))
        
        # Item 2b: OMEGA profiles (separate line item)
        if omega_kg > 0:
            item_number += 1
            unit_price = self._get_unit_price(BudgetCategory.MADRES, "kg", treatment)
            
            self.items.append(BudgetLineItem(
                item_number=item_number,
                category=BudgetCategory.MADRES,
                description="Fornecimento e montagem de perfis OMEGA 200 galvanizados para fixação de painéis",
                quantity=round(omega_kg, 2),
                unit="kg",
                unit_price=unit_price,
                total_price=omega_kg * unit_price,
                material_code="GALV",
                material_spec="Aço Galvanizado S280GD",
                weight_kg=omega_kg,
                source="excel_flysteel",
                confidence=confidence,
                notes="Perfis OMEGA 200 - fixação de painéis de cobertura/fachada"
            ))
        
        # Item 3: Pintura Intumescente (apenas estrutura não galvanizada)
        if estrutura_kg > 0:
            item_number += 1
            unit_price = self._get_unit_price(BudgetCategory.PINTURA_INTUMESCENTE, "kg", treatment)
            
            self.items.append(BudgetLineItem(
                item_number=item_number,
                category=BudgetCategory.PINTURA_INTUMESCENTE,
                description="Serviço de aplicação de pintura intumescente R60 TC 750º",
                quantity=round(estrutura_kg, 2),  # Same as structure weight
                unit="kg",
                unit_price=unit_price,
                total_price=estrutura_kg * unit_price,
                weight_kg=estrutura_kg,
                source="excel_flysteel",
                confidence=confidence,
                notes="Pintura intumescente aplicada apenas em aço não galvanizado"
            ))
        
        # Item 4: Outros elementos (Omegas, etc.)
        outros_kg = excel_data.get('outros_kg', 0)
        if outros_kg > 0:
            item_number += 1
            unit_price = self._get_unit_price(BudgetCategory.ACESSORIOS, "kg", treatment)
            
            self.items.append(BudgetLineItem(
                item_number=item_number,
                category=BudgetCategory.ACESSORIOS,
                description="Acessórios e elementos de ligação (Omegas, fixações)",
                quantity=round(outros_kg, 2),
                unit="kg",
                unit_price=unit_price,
                total_price=outros_kg * unit_price,
                weight_kg=outros_kg,
                source="excel_flysteel",
                confidence=confidence,
                notes="Elementos auxiliares"
            ))
        
        # Process Revestimentos if present
        revestimentos = excel_data.get('revestimentos', [])
        if revestimentos:
            item_number = self._process_revestimentos(revestimentos, treatment, item_number)
        
        return item_number
    
    def _process_revestimentos(self, revestimentos: List[Dict], treatment: str, start_num: int) -> int:
        """
        Process Revestimentos (cladding) items from FLYSTEEL Excel.
        Groups items by category and generates budget line items.
        """
        item_number = start_num
        
        # Group items by category and aggregate
        grouped = {}
        for item in revestimentos:
            cat = item.get('category', 'revestimentos')
            unit = item.get('unit', 'un')
            key = (cat, unit)
            
            if key not in grouped:
                grouped[key] = {
                    'items': [],
                    'total_quantity': 0,
                    'category': cat,
                    'unit': unit
                }
            
            grouped[key]['items'].append(item)
            grouped[key]['total_quantity'] += item.get('quantity', 0)
        
        # Generate budget items for each group
        for (cat, unit), group_data in grouped.items():
            items = group_data['items']
            total_qty = group_data['total_quantity']
            
            if total_qty <= 0:
                continue
            
            # Generate description based on category and items
            if cat == 'cobertura':
                if unit == 'm2':
                    desc = self._generate_cobertura_description(items)
                    budget_cat = BudgetCategory.COBERTURA
                elif unit == 'ml':
                    desc = "Fornecimento e montagem de remates de cobertura (cume, anticume, rufos)"
                    budget_cat = BudgetCategory.COBERTURA
                else:
                    desc = "Fornecimento de áreas de luz / claraboias para cobertura"
                    budget_cat = BudgetCategory.COBERTURA
            elif cat == 'fachada':
                if unit == 'm2':
                    desc = self._generate_fachada_description(items)
                    budget_cat = BudgetCategory.FACHADA
                elif unit == 'ml':
                    desc = "Fornecimento e montagem de remates de fachada"
                    budget_cat = BudgetCategory.FACHADA
                else:
                    desc = "Acessórios de fachada"
                    budget_cat = BudgetCategory.FACHADA
            elif cat == 'acessorios':
                desc = "Fornecimento de parafusos e acessórios de fixação"
                budget_cat = BudgetCategory.ACESSORIOS
            elif cat == 'divisorias' or cat == 'divisória' or cat == 'divisórias':
                if unit == 'm2':
                    desc = self._generate_divisorias_description(items)
                    budget_cat = BudgetCategory.REVESTIMENTOS  # Use REVESTIMENTOS category for pricing
                elif unit == 'ml':
                    desc = "Fornecimento e montagem de remates de divisórias interiores"
                    budget_cat = BudgetCategory.REVESTIMENTOS
                else:
                    desc = "Acessórios para divisórias interiores"
                    budget_cat = BudgetCategory.ACESSORIOS
            elif cat == 'caleiros':
                if unit == 'ml':
                    desc = "Fornecimento e montagem de caleiros em chapa, incluindo tubos de queda"
                    budget_cat = BudgetCategory.CALEIROS
                else:
                    desc = "Acessórios de drenagem e caleiros"
                    budget_cat = BudgetCategory.CALEIROS
            else:
                desc = f"Revestimentos diversos ({', '.join([i.get('designation', '') for i in items[:3]])})"
                budget_cat = BudgetCategory.REVESTIMENTOS
            
            item_number += 1
            unit_price = self._get_unit_price(budget_cat, unit, treatment)
            
            # Detailed notes with item breakdown
            notes_items = [f"{i.get('designation', 'Item')}: {i.get('quantity', 0)} {i.get('unit', 'un')}" 
                          for i in items[:5]]
            notes = "Itens incluídos: " + "; ".join(notes_items)
            if len(items) > 5:
                notes += f"; ... e mais {len(items) - 5} itens"
            
            self.items.append(BudgetLineItem(
                item_number=item_number,
                category=budget_cat,
                description=desc,
                quantity=round(total_qty, 2),
                unit=unit,
                unit_price=unit_price,
                total_price=total_qty * unit_price,
                area_m2=total_qty if unit == 'm2' else 0,
                length_ml=total_qty if unit == 'ml' else 0,
                source="excel_flysteel_revestimentos",
                confidence=0.90,
                notes=notes
            ))
            
            print(f"[BudgetCalculator] + Revestimento: {budget_cat} - {total_qty} {unit}")
        
        return item_number
    
    def _generate_cobertura_description(self, items: List[Dict]) -> str:
        """Generate professional description for cobertura items"""
        # Find main panel item
        panel_items = [i for i in items if 'painel' in i.get('designation', '').lower()]
        
        if panel_items:
            panel = panel_items[0].get('designation', '')
            if 'rocha' in panel.lower():
                return ("Fornecimento e montagem de painel de lã de rocha PC1000/50mm "
                       "incluindo áreas de luz e todos os remates e acessórios para uma boa montagem")
            elif 'pir' in panel.lower() or 'poliuret' in panel.lower():
                return ("Fornecimento e montagem de cobertura em Painel PIR 50mm "
                       "incluindo todos os remates e acessórios para uma boa montagem")
        
        return ("Fornecimento e montagem de cobertura "
               "incluindo todos os remates e acessórios para uma boa montagem")
    
    def _generate_fachada_description(self, items: List[Dict]) -> str:
        """Generate professional description for fachada items"""
        # Find main panel item
        panel_items = [i for i in items if 'painel' in i.get('designation', '').lower()]
        
        if panel_items:
            panel = panel_items[0].get('designation', '')
            if 'rocha' in panel.lower():
                return ("Fornecimento e montagem de fachada em painel lã de rocha FTBPFO1000/50mm DS "
                       "nas cores standard catálogo, incluindo todos os remates e acessórios")
            elif 'pir' in panel.lower() or 'poliuret' in panel.lower():
                return ("Fornecimento e montagem de fachada em painel PIR Micronervurado "
                       "incluindo todos os remates e acessórios")
        
        return ("Fornecimento e montagem de fachada em painel 50mm "
               "incluindo todos os remates e acessórios para uma boa montagem")
    
    def _generate_divisorias_description(self, items: List[Dict]) -> str:
        """Generate professional description for divisórias (interior partitions)"""
        # Find main panel item
        panel_items = [i for i in items if 'painel' in i.get('designation', '').lower() 
                       or 'pm1' in i.get('designation', '').lower()]
        
        if panel_items:
            panel = panel_items[0].get('designation', '')
            # Extract thickness if mentioned
            thickness = '150mm'  # default
            if '100' in panel:
                thickness = '100mm'
            elif '150' in panel:
                thickness = '150mm'
            elif '200' in panel:
                thickness = '200mm'
            
            if 'rocha' in panel.lower() or 'pm1' in panel.lower():
                return (f"Fornecimento e montagem de divisórias interiores em painel lã de rocha "
                       f"com {thickness} de espessura, incluindo remates em todo o perímetro "
                       f"e todos os acessórios para uma boa montagem e estanqueidade")
        
        return ("Fornecimento e montagem de divisórias interiores em painel sandwich "
               "incluindo todos os remates e acessórios para uma boa montagem")
    
    def _process_pdf_only(self, pdf_data: Dict, treatment: str, start_num: int) -> int:
        """Process PDF data only"""
        item_number = start_num
        bom_items = pdf_data.get('bom_items', [])
        
        for bom_item in bom_items:
            description = bom_item.get('description', '')
            quantity = float(bom_item.get('quantity', 1))
            pdf_unit = bom_item.get('unit', '').lower()
            
            category = ItemCategorizer.categorize(description)
            unit = ItemCategorizer.get_unit(category, description)
            
            if quantity > 0:
                item_number += 1
                unit_price = self._get_unit_price(category, unit, treatment)
                
                self.items.append(BudgetLineItem(
                    item_number=item_number,
                    category=category,
                    description=description,
                    quantity=quantity,
                    unit=unit,
                    unit_price=unit_price,
                    total_price=quantity * unit_price,
                    source="pdf",
                    confidence=0.70
                ))
        
        return item_number
    
    def _get_unit_price(self, category: str, unit: str, treatment: str) -> float:
        """Get price per unit for a category"""
        base_prices_kg = {
            BudgetCategory.ESTRUTURA_METALICA: self.material.base_price_eur_kg + 1.00,  # Material + fabrication
            BudgetCategory.MADRES: 1.15,  # Madres galvanizadas (preço FLYSTEEL)
            BudgetCategory.PINTURA_INTUMESCENTE: 0.028,
            BudgetCategory.ACESSORIOS: 1.20,  # Omegas e acessórios
        }
        
        base_prices_m2 = {
            BudgetCategory.COBERTURA: 29.50,
            BudgetCategory.FACHADA: 29.30,
            BudgetCategory.PINTURA_INTUMESCENTE: 28.0,
            BudgetCategory.REVESTIMENTOS: 28.0,
        }
        
        base_prices_ml = {
            BudgetCategory.CALEIROS: 40.0,
            BudgetCategory.ACESSORIOS: 9.0,
            BudgetCategory.COBERTURA: 15.0,  # Remates cobertura (cume, anticume)
            BudgetCategory.FACHADA: 15.0,    # Remates fachada
        }
        
        base_prices_un = {
            BudgetCategory.PORTAS: 330.0,
            BudgetCategory.COBERTURA: 21.0,  # Claraboias/areas de luz
            BudgetCategory.ACESSORIOS: 0.05,  # Parafusos ~€0.05/un
            BudgetCategory.FACHADA: 15.0,  # Acessórios de fachada
        }
        
        # Get base price (normalize unit for comparison)
        unit_normalized = unit.lower().strip()
        
        if unit_normalized == "kg":
            base = base_prices_kg.get(category, 2.00)
        elif unit_normalized in ["m²", "m2"]:
            base = base_prices_m2.get(category, 25.0)
        elif unit_normalized == "ml":
            base = base_prices_ml.get(category, 15.0)
        else:
            base = base_prices_un.get(category, 50.0)
        
        # Add treatment cost for kg items
        if unit == "kg" and category == BudgetCategory.ESTRUTURA_METALICA:
            treatment_addon = {
                "none": 0,
                "galvanizado": 0.45,
                "powder_coating_standard": 0.30,
                "powder_coating_qualicoat": 0.45,
            }
            base += treatment_addon.get(treatment, 0.30)
        
        return base
    
    def _generate_category_description_v2(self, category: str, treatment: str) -> str:
        """Generate professional description for a category"""
        material_name = self.material.name
        
        if category == BudgetCategory.ESTRUTURA_METALICA:
            treatment_type = "pintura" if "powder" in treatment or "coating" in treatment else "galvanizado"
            return DescriptionGenerator.generate_structure_description("", self.material.code, treatment_type)
        elif category == BudgetCategory.PINTURA_INTUMESCENTE:
            return DescriptionGenerator.generate_painting_description("R60")
        elif category == BudgetCategory.CALEIROS:
            return DescriptionGenerator.generate_gutter_description("duplo")
        elif category == BudgetCategory.COBERTURA:
            return DescriptionGenerator.generate_roof_description("la_rocha", 50)
        elif category == BudgetCategory.FACHADA:
            return DescriptionGenerator.generate_facade_description("la_rocha", 50)
        elif category == BudgetCategory.PORTAS:
            return DescriptionGenerator.generate_door_description("emergencia", "900x2150")
        else:
            return "Fornecimento e montagem de acessórios e remates diversos"
    
    def _generate_summary(self, project_name: str, project_reference: str,
                         client_name: str, has_dxf: bool, has_pdf: bool,
                         reconciliation_results: List[ReconciliationResult]):
        """Generate budget summary with sections"""
        # Group items by category
        sections_dict: Dict[str, BudgetSection] = {}
        
        for item in self.items:
            if item.category not in sections_dict:
                sections_dict[item.category] = BudgetSection(
                    category=item.category,
                    category_name=BudgetCategory.get_display_name(item.category),
                    items=[],
                    subtotal=0.0
                )
            sections_dict[item.category].items.append(item)
            sections_dict[item.category].subtotal += item.total_price
        
        # Sort sections by order
        sorted_sections = sorted(
            sections_dict.values(),
            key=lambda s: BudgetCategory.get_order(s.category)
        )
        
        # Calculate totals
        subtotal = sum(item.total_price for item in self.items)
        iva_rate = 23.0
        iva_value = subtotal * (iva_rate / 100)
        total_com_iva = subtotal + iva_value
        
        # Metrics
        total_weight = sum(item.weight_kg for item in self.items)
        total_area = sum(item.area_m2 for item in self.items)
        total_length = sum(item.length_ml for item in self.items)
        
        # Unit description
        unit_desc = f"{self.unit_multiplier} unidade" + ("s" if self.unit_multiplier > 1 else "")
        
        self.summary = BudgetSummary(
            project_name=project_name,
            project_reference=project_reference,
            created_at=datetime.now().isoformat(),
            client_name=client_name,
            primary_material=self.material.code,
            material_name=self.material.name,
            unit_multiplier=self.unit_multiplier,
            unit_description=unit_desc,
            has_dxf=has_dxf,
            has_pdf=has_pdf,
            reconciliation_results=reconciliation_results,
            sections=sorted_sections,
            subtotal=subtotal,
            iva_rate=iva_rate,
            iva_value=iva_value,
            total_com_iva=total_com_iva,
            total_weight_kg=total_weight,
            total_area_m2=total_area,
            total_length_ml=total_length
        )


def calculate_quick_estimate(weight_kg: float, complexity: str = "medium",
                            material_code: str = "S275") -> Dict[str, float]:
    """Quick estimation without detailed geometry"""
    material = MaterialDatabase.get_material(material_code)
    
    complexity_factors = {"low": 1.0, "medium": 1.5, "high": 2.0}
    factor = complexity_factors.get(complexity, 1.5)
    base_rate = (material.base_price_eur_kg + 1.50) * factor
    
    return {
        "estimated_total": round(weight_kg * base_rate, 2),
        "price_per_kg": round(base_rate, 2),
        "complexity_factor": factor,
        "material": material.name
    }


def get_available_materials() -> List[Dict]:
    """Get list of available materials for frontend"""
    return [m.to_dict() for m in MaterialDatabase.get_all()]
