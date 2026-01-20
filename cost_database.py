"""
Base de Dados de Custos - FLYSTEEL
Estrutura de preços para orçamentação de estruturas metálicas e revestimentos.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import re


@dataclass
class SteelProfile:
    """Perfil metálico com propriedades e custos."""
    code: str  # Referência (ex: 0480040011)
    designation: str  # Nome do perfil (ex: IPE 300)
    weight_per_meter: float  # kg/ml
    area_per_meter: float  # m²/ml
    # Preços por tonelada (€/ton)
    price_material: float  # Preço unitário material
    price_fabrication: float  # Fabrico
    price_assembly: float  # Montagem
    price_painting: float  # Pintura (por ton ou área)
    price_lifting: float  # Meios de elevação
    price_consumables: float  # Consumíveis
    price_transport: float  # Transporte
    is_galvanized: bool = False  # Se é galvanizado
    
    @property
    def weight_based_price_per_kg(self) -> float:
        """Preço baseado em peso (€/kg) - exclui pintura."""
        return (self.price_material + self.price_fabrication + 
                self.price_assembly + self.price_lifting + 
                self.price_consumables + self.price_transport)
    
    @property
    def painting_price_per_m2(self) -> float:
        """Preço de pintura por m²."""
        return self.price_painting
    
    def calculate_cost(self, length_meters: float) -> dict:
        """
        Calcula o custo para um comprimento dado.
        
        Nota: Os preços são em €/kg EXCEPTO pintura que é em €/m²
        """
        weight_kg = length_meters * self.weight_per_meter
        area_m2 = length_meters * self.area_per_meter
        
        # Custos baseados em peso (€/kg)
        cost_material = weight_kg * self.price_material
        cost_fabrication = weight_kg * self.price_fabrication
        cost_assembly = weight_kg * self.price_assembly
        cost_lifting = weight_kg * self.price_lifting
        cost_consumables = weight_kg * self.price_consumables
        cost_transport = weight_kg * self.price_transport
        
        # Custo de pintura baseado em área (€/m²)
        cost_painting = area_m2 * self.price_painting
        
        total_cost = (cost_material + cost_fabrication + cost_assembly + 
                     cost_painting + cost_lifting + cost_consumables + cost_transport)
        
        return {
            "designation": self.designation,
            "length_m": length_meters,
            "weight_kg": weight_kg,
            "area_m2": area_m2,
            "cost_material": cost_material,
            "cost_fabrication": cost_fabrication,
            "cost_assembly": cost_assembly,
            "cost_painting": cost_painting,
            "cost_lifting": cost_lifting,
            "cost_consumables": cost_consumables,
            "cost_transport": cost_transport,
            "total_cost": total_cost
        }


@dataclass
class CladdingItem:
    """Item de revestimento (fachada ou cobertura)."""
    designation: str
    unit: str  # m², ml, un
    price_material: float
    price_fabrication: float
    price_assembly: float
    price_painting: float
    price_lifting: float
    price_consumables: float
    price_transport: float
    
    @property
    def total_price_per_unit(self) -> float:
        """Preço total por unidade."""
        return (self.price_material + self.price_fabrication + 
                self.price_assembly + self.price_painting + 
                self.price_lifting + self.price_consumables + 
                self.price_transport)
    
    def calculate_cost(self, quantity: float) -> dict:
        """Calcula o custo para uma quantidade dada."""
        return {
            "designation": self.designation,
            "quantity": quantity,
            "unit": self.unit,
            "cost_material": quantity * self.price_material,
            "cost_fabrication": quantity * self.price_fabrication,
            "cost_assembly": quantity * self.price_assembly,
            "cost_painting": quantity * self.price_painting,
            "cost_lifting": quantity * self.price_lifting,
            "cost_consumables": quantity * self.price_consumables,
            "cost_transport": quantity * self.price_transport,
            "total_cost": quantity * self.total_price_per_unit
        }


class CostDatabase:
    """Base de dados centralizada de custos."""
    
    def __init__(self):
        self._init_steel_profiles()
        self._init_facade_cladding()
        self._init_roof_cladding()
        self._init_accessories()
    
    def _init_steel_profiles(self):
        """Inicializa perfis metálicos baseado na estrutura de custos FLYSTEEL."""
        self.steel_profiles: Dict[str, SteelProfile] = {}
        
        # Dados extraídos do Excel "Estrutura de custos - Estrutura metálica.xlsx"
        profiles_data = [
            # (code, designation, kg/ml, m²/ml, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp)
            ("0480040011", "IPE 300", 42.2, 1.16, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040009", "IPE 240", 30.7, 0.922, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040015", "IPE 450", 77.6, 1.61, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040008", "IPE 220", 26.2, 0.848, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040010", "IPE 270", 30.7, 0.92, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040004", "IPE 140", 12.9, 0.551, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040003", "IPE 120", 10.4, 0.475, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040005", "IPE 160", 15.8, 0.623, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040006", "IPE 180", 18.8, 0.699, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040007", "IPE 200", 22.4, 0.773, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040012", "IPE 330", 49.1, 1.252, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040013", "IPE 360", 57.1, 1.356, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040014", "IPE 400", 66.3, 1.467, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040016", "IPE 500", 90.7, 1.782, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040017", "IPE 550", 106.0, 1.944, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480040018", "IPE 600", 122.0, 2.106, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # HEB profiles
            ("0480030010", "HEB 100", 20.4, 0.567, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030011", "HEB 120", 26.7, 0.686, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030012", "HEB 140", 33.7, 0.805, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030013", "HEB 160", 42.6, 0.924, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030014", "HEB 180", 51.2, 1.043, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030015", "HEB 200", 61.3, 1.162, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030016", "HEB 220", 71.5, 1.294, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030017", "HEB 240", 83.2, 1.426, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030018", "HEB 260", 93.0, 1.545, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030019", "HEB 280", 103.0, 1.664, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030020", "HEB 300", 117.0, 1.783, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030021", "HEB 320", 127.0, 1.889, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030022", "HEB 340", 134.0, 1.969, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030023", "HEB 360", 142.0, 2.049, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030024", "HEB 400", 155.0, 2.196, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030025", "HEB 450", 171.0, 2.396, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480030026", "HEB 500", 187.0, 2.596, 0.9, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # HEA profiles
            ("0480020010", "HEA 100", 16.7, 0.560, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020011", "HEA 120", 19.9, 0.666, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020012", "HEA 140", 24.7, 0.772, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020013", "HEA 160", 30.4, 0.878, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020014", "HEA 180", 35.5, 0.984, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020015", "HEA 200", 42.3, 1.090, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020016", "HEA 220", 50.5, 1.209, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020017", "HEA 240", 60.3, 1.328, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020018", "HEA 260", 68.2, 1.447, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020019", "HEA 280", 76.4, 1.566, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480020020", "HEA 300", 88.3, 1.685, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # UPN profiles
            ("0480050005", "UPN 80", 8.64, 0.362, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050006", "UPN 100", 10.6, 0.424, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050007", "UPN 120", 13.4, 0.494, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050008", "UPN 140", 16.0, 0.564, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050009", "UPN 160", 18.8, 0.634, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050010", "UPN 180", 22.0, 0.710, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050011", "UPN 200", 25.3, 0.786, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050012", "UPN 220", 29.4, 0.862, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050013", "UPN 240", 33.2, 0.938, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050014", "UPN 260", 37.9, 1.014, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050015", "UPN 280", 41.8, 1.090, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0480050016", "UPN 300", 46.2, 1.166, 0.85, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # Tubos redondos
            ("0550010060", "TUBO RED. 88.9*3.2", 6.76, 0.28, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550010050", "TUBO RED. 60.3*3.2", 4.51, 0.19, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550010070", "TUBO RED. 114.3*3.6", 9.83, 0.36, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550010080", "TUBO RED. 139.7*4.0", 13.4, 0.44, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550010090", "TUBO RED. 168.3*4.5", 18.2, 0.53, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # Tubos rectangulares (RHS)
            ("0550020040", "RHS 100x50x3", 6.71, 0.30, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020050", "RHS 100x50x4", 8.59, 0.30, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020060", "RHS 120x60x4", 10.7, 0.36, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020070", "RHS 150x100x5", 18.6, 0.50, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020080", "RHS 200x100x5", 23.2, 0.60, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020090", "RHS 200x100x6", 27.4, 0.60, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020100", "RHS 250x150x6", 36.6, 0.80, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550020110", "RHS 300x200x8", 60.5, 1.00, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # Tubos quadrados (SHS)
            ("0550030040", "SHS 60x60x3", 5.29, 0.24, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550030050", "SHS 80x80x4", 9.22, 0.32, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550030060", "SHS 100x100x4", 11.7, 0.40, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550030070", "SHS 100x100x5", 14.4, 0.40, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550030080", "SHS 120x120x5", 17.5, 0.48, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550030090", "SHS 150x150x6", 26.4, 0.60, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0550030100", "SHS 200x200x8", 47.7, 0.80, 1.25, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            # Madres galvanizadas (preços diferentes - sem montagem pesada)
            ("0410010013", "MADRE Z 170*56*15 ESP. 1.5MM", 3.54, 0.604, 1.15, 0, 0.2, 0, 0.05, 0.04, 0.03),
            ("0410010005", "MADRE C 170*56*15 ESP. 1.5MM", 3.54, 0.604, 1.15, 0, 0.2, 0, 0.05, 0.04, 0.03),
            ("0410010015", "MADRE C 220*68*18 ESP. 2MM", 5.85, 0.75, 1.15, 0, 0.2, 0, 0.05, 0.04, 0.03),
            ("0410010016", "MADRE Z 200*60*15 ESP. 2MM", 5.10, 0.68, 1.15, 0, 0.2, 0, 0.05, 0.04, 0.03),
            ("0410010017", "MADRE Z 250*70*20 ESP. 2.5MM", 7.85, 0.82, 1.15, 0, 0.2, 0, 0.05, 0.04, 0.03),
            # Omegas
            ("0410020001", "OMEGA 50", 2.27, 0.388, 1.2, 0, 0.2, 0, 0.05, 0.04, 0.03),
            ("0410020002", "OMEGA 80", 3.15, 0.45, 1.2, 0, 0.2, 0, 0.05, 0.04, 0.03),
            # Chapas
            ("0240120008", "CHAPA PRETA 8MM", 62.8, 1.0, 1.8, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0240120010", "CHAPA PRETA 10MM", 78.5, 1.0, 1.8, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0240120012", "CHAPA PRETA 12MM", 94.2, 1.0, 1.8, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0240120013", "CHAPA PRETA 15MM", 120.0, 2.0, 1.8, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0240120020", "CHAPA PRETA 20MM", 157.0, 2.0, 1.8, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
            ("0240120025", "CHAPA PRETA 25MM", 196.0, 2.0, 1.8, 0.25, 0.2, 13, 0.05, 0.04, 0.03),
        ]
        
        for data in profiles_data:
            code, designation, kg_ml, m2_ml, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp = data
            profile = SteelProfile(
                code=code,
                designation=designation,
                weight_per_meter=kg_ml,
                area_per_meter=m2_ml,
                price_material=pr_unit,
                price_fabrication=fabrico,
                price_assembly=montagem,
                price_painting=pintura,
                price_lifting=m_elev,
                price_consumables=consum,
                price_transport=transp,
                is_galvanized="GALVANIZADA" in designation.upper() or "MADRE" in designation.upper()
            )
            # Indexar por designação normalizada
            key = self._normalize_profile_name(designation)
            self.steel_profiles[key] = profile
            # Também indexar por código
            self.steel_profiles[code] = profile
    
    def _init_facade_cladding(self):
        """Inicializa revestimentos de fachada."""
        self.facade_items: Dict[str, CladdingItem] = {}
        
        # Dados do Excel "Estrutura de custos - Revestimentos fachada.xlsx"
        items_data = [
            # (designation, unit, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp)
            ("PAINEL FACHADA LA ROCHA 50MM", "m²", 23, 0, 5, 0, 1.3, 0, 0),
            ("PAINEL FACHADA PIR 50MM", "m²", 22, 0, 5, 0, 1.3, 0, 0),
            ("PAINEL FACHADA POLIURETANO 30MM", "m²", 18, 0, 5, 0, 1.3, 0, 0),
            ("CHAPA SIMPLES FACHADA", "m²", 12, 0, 4, 0, 1, 0, 0),
            ("CHAPA SIMPLES PRELACADA", "m²", 14, 0, 4, 0, 1, 0, 0),
            ("REMATES FACHADA", "ml", 9, 0, 0, 0, 0, 0, 0),
            ("PARAFUSOS FACHADA", "un", 1, 0, 0, 0, 0, 0, 0),
            ("CONTRA FACHADA CHAPA SIMPLES", "m²", 10, 0, 3, 0, 1, 0, 0),
        ]
        
        for data in items_data:
            designation, unit, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp = data
            item = CladdingItem(
                designation=designation,
                unit=unit,
                price_material=pr_unit,
                price_fabrication=fabrico,
                price_assembly=montagem,
                price_painting=pintura,
                price_lifting=m_elev,
                price_consumables=consum,
                price_transport=transp
            )
            key = self._normalize_item_name(designation)
            self.facade_items[key] = item
    
    def _init_roof_cladding(self):
        """Inicializa revestimentos de cobertura."""
        self.roof_items: Dict[str, CladdingItem] = {}
        
        # Dados do Excel "Estrutura de custos - Revestimentos Cobertura.xlsx"
        items_data = [
            # (designation, unit, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp)
            ("PAINEL COBERTURA LA ROCHA 50MM", "m²", 23.5, 0, 5, 0, 1, 0, 0),
            ("PAINEL COBERTURA LA ROCHA 80MM", "m²", 28, 0, 5, 0, 1, 0, 0),
            ("PAINEL COBERTURA PIR 50MM", "m²", 22, 0, 5, 0, 1, 0, 0),
            ("PAINEL COBERTURA POLIURETANO 30MM", "m²", 18, 0, 5, 0, 1, 0, 0),
            ("CHAPA SIMPLES COBERTURA", "m²", 10, 0, 4, 0, 1, 0, 0),
            ("ANTICUME", "ml", 7, 0, 0, 0, 0, 0, 0),
            ("CUME", "ml", 12, 0, 0, 0, 0, 0, 0),
            ("PARAFUSOS COBERTURA", "un", 1, 0, 0, 0, 0, 0, 0),
            ("CLARABOIA FIXA 1.0X1.0", "un", 19, 0, 2, 0, 0, 0, 0),
            ("CLARABOIA FIXA 1.5X1.5", "un", 35, 0, 3, 0, 0, 0, 0),
            ("AREA DE LUZ", "m²", 19, 0, 2, 0, 0, 0, 0),
            ("CALEIRA DUPLA ISOLADA", "ml", 35, 0, 5, 0, 0, 0, 0),
            ("CALEIRA SIMPLES GALVANIZADA", "ml", 18, 0, 3, 0, 0, 0, 0),
        ]
        
        for data in items_data:
            designation, unit, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp = data
            item = CladdingItem(
                designation=designation,
                unit=unit,
                price_material=pr_unit,
                price_fabrication=fabrico,
                price_assembly=montagem,
                price_painting=pintura,
                price_lifting=m_elev,
                price_consumables=consum,
                price_transport=transp
            )
            key = self._normalize_item_name(designation)
            self.roof_items[key] = item
    
    def _init_accessories(self):
        """Inicializa acessórios diversos."""
        self.accessories: Dict[str, CladdingItem] = {}
        
        items_data = [
            ("PORTA EMERGENCIA 900X2150", "un", 280, 0, 50, 0, 0, 0, 0),
            ("PORTA EMERGENCIA 1200X2150", "un", 350, 0, 50, 0, 0, 0, 0),
            ("PORTA SECTORIAL 3000X3000", "un", 1800, 0, 200, 0, 50, 0, 0),
            ("PORTA SECTORIAL 4000X4000", "un", 2400, 0, 250, 0, 50, 0, 0),
            ("PORTAO BASCULANTE 3000X3000", "un", 1200, 0, 150, 0, 30, 0, 0),
            ("JANELA ALUMINIO", "m²", 150, 0, 30, 0, 0, 0, 0),
            ("PINTURA INTUMESCENTE R30", "m²", 18, 0, 0, 0, 0, 0, 0),
            ("PINTURA INTUMESCENTE R60", "m²", 28, 0, 0, 0, 0, 0, 0),
            ("PINTURA INTUMESCENTE R90", "m²", 40, 0, 0, 0, 0, 0, 0),
            ("GALVANIZACAO", "kg", 0.45, 0, 0, 0, 0, 0, 0),
        ]
        
        for data in items_data:
            designation, unit, pr_unit, fabrico, montagem, pintura, m_elev, consum, transp = data
            item = CladdingItem(
                designation=designation,
                unit=unit,
                price_material=pr_unit,
                price_fabrication=fabrico,
                price_assembly=montagem,
                price_painting=pintura,
                price_lifting=m_elev,
                price_consumables=consum,
                price_transport=transp
            )
            key = self._normalize_item_name(designation)
            self.accessories[key] = item
    
    def _normalize_profile_name(self, name: str) -> str:
        """Normaliza nome de perfil para pesquisa."""
        name = name.upper().strip()
        # Remover espaços extras
        name = re.sub(r'\s+', ' ', name)
        # Normalizar separadores
        name = name.replace('*', 'X').replace('×', 'X')
        return name
    
    def _normalize_item_name(self, name: str) -> str:
        """Normaliza nome de item para pesquisa."""
        name = name.upper().strip()
        name = re.sub(r'\s+', ' ', name)
        # Normalizar acentos
        replacements = {
            'Ã': 'A', 'Á': 'A', 'À': 'A', 'Â': 'A',
            'É': 'E', 'È': 'E', 'Ê': 'E',
            'Í': 'I', 'Ì': 'I', 'Î': 'I',
            'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Õ': 'O',
            'Ú': 'U', 'Ù': 'U', 'Û': 'U',
            'Ç': 'C'
        }
        for old, new in replacements.items():
            name = name.replace(old, new)
        return name
    
    def find_profile(self, search_term: str) -> Optional[SteelProfile]:
        """Procura um perfil por designação ou código."""
        normalized = self._normalize_profile_name(search_term)
        
        # Procura exacta
        if normalized in self.steel_profiles:
            return self.steel_profiles[normalized]
        
        # Procura parcial
        for key, profile in self.steel_profiles.items():
            if normalized in key or key in normalized:
                return profile
        
        # Procura por padrão de perfil (ex: "IPE300" -> "IPE 300")
        match = re.match(r'(IPE|HEB|HEA|UPN|RHS|SHS)[\s]?(\d+)', normalized)
        if match:
            profile_type = match.group(1)
            size = match.group(2)
            search_key = f"{profile_type} {size}"
            if search_key in self.steel_profiles:
                return self.steel_profiles[search_key]
        
        return None
    
    def find_cladding(self, search_term: str, category: str = "all") -> Optional[CladdingItem]:
        """Procura um item de revestimento."""
        normalized = self._normalize_item_name(search_term)
        
        sources = []
        if category in ["all", "facade"]:
            sources.append(self.facade_items)
        if category in ["all", "roof"]:
            sources.append(self.roof_items)
        if category in ["all", "accessories"]:
            sources.append(self.accessories)
        
        for source in sources:
            # Procura exacta
            if normalized in source:
                return source[normalized]
            
            # Procura parcial
            for key, item in source.items():
                if normalized in key or key in normalized:
                    return item
                # Verificar palavras-chave
                keywords = normalized.split()
                if all(kw in key for kw in keywords):
                    return item
        
        return None
    
    def get_all_profiles(self) -> List[SteelProfile]:
        """Retorna todos os perfis únicos."""
        seen = set()
        profiles = []
        for profile in self.steel_profiles.values():
            if profile.designation not in seen:
                seen.add(profile.designation)
                profiles.append(profile)
        return sorted(profiles, key=lambda p: p.designation)
    
    def get_all_cladding(self) -> Dict[str, List[CladdingItem]]:
        """Retorna todos os itens de revestimento organizados por categoria."""
        # Use dict to deduplicate by designation
        def unique_items(items_dict):
            seen = set()
            result = []
            for item in items_dict.values():
                if item.designation not in seen:
                    seen.add(item.designation)
                    result.append(item)
            return result
        
        return {
            "facade": unique_items(self.facade_items),
            "roof": unique_items(self.roof_items),
            "accessories": unique_items(self.accessories)
        }


# Instância global para uso na aplicação
cost_db = CostDatabase()


def calculate_steel_structure_cost(profiles: List[dict]) -> dict:
    """
    Calcula o custo total de uma estrutura metálica.
    
    Args:
        profiles: Lista de dicts com {"profile": "IPE 300", "length": 100}
    
    Returns:
        Dicionário com custos detalhados.
    """
    total_weight = 0
    total_cost = 0
    items = []
    
    for p in profiles:
        profile = cost_db.find_profile(p.get("profile", ""))
        length = p.get("length", 0)
        
        if profile and length > 0:
            cost_detail = profile.calculate_cost(length)
            items.append(cost_detail)
            total_weight += cost_detail["weight_kg"]
            total_cost += cost_detail["total_cost"]
    
    return {
        "items": items,
        "total_weight_kg": total_weight,
        "total_weight_ton": total_weight / 1000,
        "total_cost": total_cost
    }


def calculate_cladding_cost(items: List[dict]) -> dict:
    """
    Calcula o custo total de revestimentos.
    
    Args:
        items: Lista de dicts com {"item": "PAINEL FACHADA", "quantity": 1000}
    
    Returns:
        Dicionário com custos detalhados.
    """
    total_cost = 0
    calculated_items = []
    
    for i in items:
        item = cost_db.find_cladding(i.get("item", ""))
        quantity = i.get("quantity", 0)
        
        if item and quantity > 0:
            cost_detail = item.calculate_cost(quantity)
            calculated_items.append(cost_detail)
            total_cost += cost_detail["total_cost"]
    
    return {
        "items": calculated_items,
        "total_cost": total_cost
    }
