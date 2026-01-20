"""
AluQuote AI - DXF Parser Module (The "Vector Eye") - ENHANCED VERSION
Extração avançada e exaustiva de geometria de ficheiros DXF
Lê escalas, todas as entidades, materiais e quantidades
PREVALÊNCIA: Quantidades do DXF prevalecem sobre PDF
"""

import ezdxf
from ezdxf.math import Vec2, Vec3
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional, Set
import math
from pathlib import Path
from collections import Counter, defaultdict
import re


@dataclass
class GeometricFeature:
    """Represents a detected geometric feature in the DXF"""
    feature_type: str
    position: Tuple[float, float]
    dimensions: Dict[str, float]
    layer: str
    entity_type: str = ""
    machining_time_mins: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_type": self.feature_type,
            "position": self.position,
            "dimensions": self.dimensions,
            "layer": self.layer,
            "entity_type": self.entity_type,
            "machining_time_mins": self.machining_time_mins
        }


@dataclass
class ProfileData:
    """Complete profile data extracted from DXF"""
    profile_id: str
    layer: str
    is_closed: bool
    perimeter_mm: float
    area_mm2: float
    bounding_box: Dict[str, float]
    centroid: Tuple[float, float]
    vertex_count: int
    entity_type: str = "UNKNOWN"
    color: Optional[int] = None
    linetype: Optional[str] = None
    features: List[GeometricFeature] = field(default_factory=list)
    complexity_score: float = 1.0
    material_hint: Optional[str] = None
    thickness_hint: Optional[float] = None
    quantity: int = 1
    length_mm: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "layer": self.layer,
            "is_closed": self.is_closed,
            "perimeter_mm": round(self.perimeter_mm, 2),
            "area_mm2": round(self.area_mm2, 2),
            "length_mm": round(self.length_mm, 2),
            "bounding_box": self.bounding_box,
            "centroid": self.centroid,
            "vertex_count": self.vertex_count,
            "entity_type": self.entity_type,
            "color": self.color,
            "linetype": self.linetype,
            "features": [f.to_dict() for f in self.features],
            "complexity_score": round(self.complexity_score, 2),
            "weight_kg": self.calculate_weight(),
            "machining_time_mins": self.calculate_machining_time(),
            "material_hint": self.material_hint,
            "thickness_hint": self.thickness_hint,
            "quantity": self.quantity
        }
    
    def calculate_weight(self, density_kg_m3: float = 2700, thickness_mm: float = None) -> float:
        """Calculate weight based on aluminum density (2700 kg/m³)"""
        if not self.is_closed or self.area_mm2 <= 0:
            # For non-closed profiles, estimate based on perimeter
            if self.perimeter_mm > 0:
                t = thickness_mm or self.thickness_hint or 2.0
                # Assume a profile section of t x t
                volume_mm3 = self.perimeter_mm * t * t
                return round((volume_mm3 / 1e9) * density_kg_m3, 4)
            return 0.0
        t = thickness_mm or self.thickness_hint or 2.0
        volume_m3 = (self.area_mm2 * t) / 1e9
        return round(volume_m3 * density_kg_m3, 4)
    
    def calculate_machining_time(self) -> float:
        """Estimate machining time based on features"""
        base_time = 2.0
        feature_time = sum(f.machining_time_mins for f in self.features)
        complexity_factor = self.complexity_score
        return round(base_time * complexity_factor + feature_time, 1)


@dataclass
class DXFScale:
    """Scale information extracted from DXF"""
    drawing_scale: float = 1.0
    units: str = "mm"
    viewport_scales: List[float] = field(default_factory=list)
    dimscale: float = 1.0
    ltscale: float = 1.0
    unit_factor: float = 1.0  # Conversion factor to mm
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "drawing_scale": self.drawing_scale,
            "units": self.units,
            "viewport_scales": self.viewport_scales,
            "dimscale": self.dimscale,
            "ltscale": self.ltscale,
            "unit_factor": self.unit_factor
        }


@dataclass 
class MaterialQuantity:
    """Material quantity extracted from DXF"""
    material_type: str
    profile_reference: str
    description: str
    quantity: int
    unit_length_mm: float
    total_length_mm: float
    unit_weight_kg: float
    total_weight_kg: float
    layer: str
    source: str
    unit_area_mm2: float = 0.0
    total_area_mm2: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_type": self.material_type,
            "profile_reference": self.profile_reference,
            "description": self.description,
            "quantity": self.quantity,
            "unit_length_mm": round(self.unit_length_mm, 2),
            "total_length_mm": round(self.total_length_mm, 2),
            "unit_weight_kg": round(self.unit_weight_kg, 4),
            "total_weight_kg": round(self.total_weight_kg, 4),
            "unit_area_mm2": round(self.unit_area_mm2, 2),
            "total_area_mm2": round(self.total_area_mm2, 2),
            "layer": self.layer,
            "source": self.source
        }


class DXFParser:
    """
    Advanced DXF Parser - The "Vector Eye" - ENHANCED VERSION
    Extração exaustiva com suporte a escalas, materiais e quantidades
    """
    
    HOLE_RADIUS_THRESHOLD_MM = 50.0
    
    # Conversão de unidades para mm
    UNIT_CONVERSION = {
        'unitless': 1.0, 'inches': 25.4, 'feet': 304.8, 'miles': 1609344.0,
        'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'km': 1000000.0,
        'microinches': 0.0000254, 'mils': 0.0254, 'yards': 914.4,
        'microns': 0.001, 'decimeters': 100.0, 'decameters': 10000.0
    }
    
    # Layers a IGNORAR (não são elementos estruturais)
    IGNORE_LAYERS = [
        # Anotações e texto
        'texto', 'textos', 'text', 'texts', 'anotacao', 'annotation',
        # Cotagem e dimensionamento
        'cotagem', 'cota', 'cotas', 'dimension', 'dim', 'dims',
        # Layers auxiliares comuns
        'defpoints', 'viewport', 'hatch', 'hatches',
        # Símbolos e apresentação
        'simbolo', 'symbol', 'simbologia', 'projecao', 'projecoes',
        # Veículos, topografia, vegetação (não estruturais)
        'veiculo', 'veiculos', 'vehicle', 'carro', 'cars',
        'topo', 'topografia', 'topography', 'terrain',
        'arvore', 'arvores', 'tree', 'vegetation', 'planta',
        # Vistas e cortes (símbolos, não geometria)
        'corte', 'alzado', 'vista', 'poligono', 'poligonos',
    ]
    
    # Padrões para identificar materiais
    MATERIAL_PATTERNS = {
        'aluminio': r'(alum[ií]nio|alu|al[\s\-_]?\d{4}|6060|6063|6005|6082|EN\s*AW)',
        'aco': r'(a[çc]o|steel|s[\s\-_]?\d{3}|inox|stainless)',
        'vidro': r'(vidro|glass|cristal|vidr)',
        'borracha': r'(borracha|rubber|epdm|silicone|vedante|seal)',
        'perfil': r'(perfil|profile|tubo|tube|barra|bar)',
        'chapa': r'(chapa|sheet|plate|panel|painel)',
        'acessorio': r'(acess[oó]rio|accessory|ferragem|hardware|dobradi[çc]a|puxador)',
    }
    
    # Padrões para extrair quantidades - MUITO CONSERVADOR
    # Apenas aceita textos que CLARAMENTE indicam quantidade
    # Evita dimensões como "50 x 20 x 15" ou "100x100"
    QUANTITY_PATTERNS = [
        r'^(\d+)\s*[xX]\s*$',  # Apenas "3x" ou "3 x" no fim da string
        r'(\d+)\s*(?:un|pcs?|pe[çc]as?|units?|unid)\b',  # "3 UN", "5 pcs"
        r'qty[:\s]*(\d+)',  # "QTY: 5"
        r'quant(?:idade)?[:\s]*(\d+)',  # "QUANTIDADE: 3"
        r'^(\d+)\s*off\b',  # "5 off" no início
    ]
    
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.doc = None
        self.msp = None
        self.profiles: List[ProfileData] = []
        self.features: List[GeometricFeature] = []
        self.file_info: Dict[str, Any] = {}
        self.scale_info: DXFScale = DXFScale()
        self.material_quantities: List[MaterialQuantity] = []
        self.texts_extracted: List[Dict[str, Any]] = []
        self.dimensions_extracted: List[Dict[str, Any]] = []
        self.blocks_analyzed: Dict[str, Dict] = {}
        self.layers_info: Dict[str, Dict] = {}
        self.entity_counts: Dict[str, int] = defaultdict(int)
        
    def parse(self) -> Dict[str, Any]:
        """Main parsing method - EXHAUSTIVE analysis"""
        try:
            self.doc = ezdxf.readfile(str(self.file_path))
            self.msp = self.doc.modelspace()
            
            # 1. Extract file info and scales
            self._extract_file_info()
            self._extract_scale_info()
            
            # 2. Analyze all layers
            self._analyze_layers()
            
            # 3. Extract ALL text entities
            self._extract_all_texts()
            
            # 4. Extract dimension entities
            self._extract_dimensions()
            
            # 5. Analyze blocks and their counts
            self._analyze_blocks_exhaustive()
            
            # 6. Extract ALL geometry types
            self._extract_all_geometry()
            
            # 7. Detect features
            self._detect_all_features()
            self._calculate_complexity()
            
            # 8. Extract and compile material quantities
            self._compile_material_quantities()
            
            # 9. Apply scale to all measurements
            self._apply_scale_corrections()
            
            return {
                "success": True,
                "file_info": self.file_info,
                "scale_info": self.scale_info.to_dict(),
                "layers": self.layers_info,
                "profiles": [p.to_dict() for p in self.profiles],
                "features_summary": self._get_features_summary(),
                "features_detail": [f.to_dict() for f in self.features],
                "material_quantities": [m.to_dict() for m in self.material_quantities],
                "blocks_analyzed": self.blocks_analyzed,
                "texts_extracted": self.texts_extracted,
                "dimensions_extracted": self.dimensions_extracted,
                "entity_counts": dict(self.entity_counts),
                "statistics": {
                    "total_profiles": len(self.profiles),
                    "total_features": len(self.features),
                    "total_perimeter_mm": sum(p.perimeter_mm * p.quantity for p in self.profiles),
                    "total_area_mm2": sum(p.area_mm2 * p.quantity for p in self.profiles if p.is_closed),
                    "total_length_mm": sum(p.length_mm * p.quantity for p in self.profiles),
                    "estimated_weight_kg": sum(p.calculate_weight() * p.quantity for p in self.profiles),
                    "estimated_machining_time_mins": sum(p.calculate_machining_time() * p.quantity for p in self.profiles),
                    "total_material_items": len(self.material_quantities),
                    "unique_layers": len(self.layers_info),
                    "total_texts": len(self.texts_extracted),
                    "total_dimensions": len(self.dimensions_extracted)
                }
            }
            
        except Exception as e:
            import traceback
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "file_info": {"filename": self.file_path.name}
            }
    
    def _extract_file_info(self):
        """Extract comprehensive file information"""
        self.file_info = {
            "filename": self.file_path.name,
            "dxf_version": self.doc.dxfversion,
            "encoding": self.doc.encoding,
            "units": self._detect_units()
        }
    
    def _detect_units(self) -> str:
        """Detect DXF units from header"""
        try:
            units = self.doc.header.get('$INSUNITS', 0)
            unit_map = {
                0: 'unitless', 1: 'inches', 2: 'feet', 3: 'miles',
                4: 'mm', 5: 'cm', 6: 'm', 7: 'km',
                8: 'microinches', 9: 'mils', 10: 'yards',
                13: 'microns', 14: 'decimeters', 15: 'decameters'
            }
            detected = unit_map.get(units, 'mm')
            self.scale_info.units = detected
            self.scale_info.unit_factor = self.UNIT_CONVERSION.get(detected, 1.0)
            return detected
        except:
            return 'mm'
    
    def _extract_scale_info(self):
        """Extract all scale-related information from DXF"""
        header = self.doc.header
        
        try:
            self.scale_info.dimscale = header.get('$DIMSCALE', 1.0)
        except:
            pass
        
        try:
            self.scale_info.ltscale = header.get('$LTSCALE', 1.0)
        except:
            pass
        
        # Check viewports
        try:
            for layout in self.doc.layouts:
                if layout.name != 'Model':
                    for entity in layout:
                        if entity.dxftype() == 'VIEWPORT':
                            try:
                                if hasattr(entity.dxf, 'view_height') and hasattr(entity.dxf, 'height'):
                                    if entity.dxf.height > 0:
                                        scale = entity.dxf.view_height / entity.dxf.height
                                        if scale != 1.0:
                                            self.scale_info.viewport_scales.append(scale)
                            except:
                                pass
        except:
            pass
        
        # Determine effective scale
        if self.scale_info.viewport_scales:
            self.scale_info.drawing_scale = self.scale_info.viewport_scales[0]
        elif self.scale_info.dimscale != 1.0:
            self.scale_info.drawing_scale = self.scale_info.dimscale
    
    def _analyze_layers(self):
        """Analyze all layers in the DXF"""
        try:
            for layer in self.doc.layers:
                layer_name = layer.dxf.name
                self.layers_info[layer_name] = {
                    "name": layer_name,
                    "color": layer.color,
                    "is_on": layer.is_on(),
                    "is_frozen": layer.is_frozen(),
                    "linetype": layer.dxf.linetype,
                    "entity_count": 0,
                    "material_hint": self._detect_material_from_name(layer_name),
                    "profiles_count": 0,
                    "total_length_mm": 0.0
                }
        except:
            pass
        
        # Count entities per layer
        for entity in self.msp:
            try:
                layer = entity.dxf.layer
                etype = entity.dxftype()
                self.entity_counts[etype] += 1
                if layer in self.layers_info:
                    self.layers_info[layer]["entity_count"] += 1
            except:
                pass
    
    def _detect_material_from_name(self, name: str) -> Optional[str]:
        """Detect material type from layer/block name"""
        name_lower = name.lower()
        for material, pattern in self.MATERIAL_PATTERNS.items():
            if re.search(pattern, name_lower, re.IGNORECASE):
                return material
        return None
    
    def _extract_all_texts(self):
        """Extract ALL text entities for analysis"""
        text_types = ['TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF']
        
        for text_type in text_types:
            for entity in self.msp.query(text_type):
                try:
                    if text_type in ['TEXT', 'ATTRIB', 'ATTDEF']:
                        content = entity.dxf.text
                        pos = (entity.dxf.insert.x, entity.dxf.insert.y)
                        height = getattr(entity.dxf, 'height', 0)
                    else:
                        content = entity.text
                        pos = (entity.dxf.insert.x, entity.dxf.insert.y)
                        height = getattr(entity.dxf, 'char_height', 0)
                    
                    if content and content.strip():
                        # Clean MTEXT formatting codes
                        clean_content = re.sub(r'\\[A-Za-z][^;]*;', '', content)
                        clean_content = re.sub(r'\{|\}', '', clean_content)
                        clean_content = clean_content.strip()
                        
                        if clean_content:
                            text_data = {
                                "content": clean_content,
                                "raw_content": content,
                                "position": pos,
                                "layer": entity.dxf.layer,
                                "type": text_type,
                                "height": height,
                                "quantity_hint": self._extract_quantity_from_text(clean_content),
                                "material_hint": self._detect_material_from_name(clean_content),
                                "dimension_values": self._extract_dimension_values(clean_content),
                                "profile_reference": self._extract_profile_reference(clean_content)
                            }
                            self.texts_extracted.append(text_data)
                except:
                    continue
    
    def _extract_quantity_from_text(self, text: str) -> Optional[int]:
        """Extract quantity from text content"""
        text_clean = text.strip()
        
        for pattern in self.QUANTITY_PATTERNS:
            match = re.search(pattern, text_clean, re.IGNORECASE)
            if match:
                try:
                    qty = int(match.group(1))
                    if 0 < qty < 10000:  # Sanity check
                        return qty
                except:
                    pass
        return None
    
    def _extract_dimension_values(self, text: str) -> List[float]:
        """Extract numeric dimension values from text"""
        values = []
        # Pattern: numbers with optional decimals
        matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*(?:mm|cm|m)?', text)
        for m in matches:
            try:
                val = float(m.replace(',', '.'))
                if 0.1 < val < 100000:  # Reasonable range
                    values.append(val)
            except:
                pass
        return values
    
    def _extract_profile_reference(self, text: str) -> Optional[str]:
        """Extract profile reference code from text"""
        # Common patterns: P-001, PERFIL_A, ALU-6060, etc.
        patterns = [
            r'([A-Z]{1,3}[-_]?\d{2,4})',
            r'(PERFIL[-_\s]*[A-Z0-9]+)',
            r'(PROFILE[-_\s]*[A-Z0-9]+)',
            r'(AL[-_]?\d{4})',
            r'(EN\s*AW[-_]?\d{4})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).upper()
        return None
    
    def _extract_dimensions(self):
        """Extract DIMENSION entities"""
        for entity in self.msp.query('DIMENSION'):
            try:
                dim_data = {
                    "type": entity.dxftype(),
                    "layer": entity.dxf.layer,
                    "measurement": None,
                    "text_override": None
                }
                
                # Try to get actual measurement
                try:
                    if hasattr(entity, 'measurement'):
                        dim_data["measurement"] = entity.measurement
                except:
                    pass
                
                # Get text override if present
                try:
                    dim_data["text_override"] = entity.dxf.text
                except:
                    pass
                
                if dim_data["measurement"] or dim_data["text_override"]:
                    self.dimensions_extracted.append(dim_data)
            except:
                continue
    
    def _analyze_blocks_exhaustive(self):
        """Analyze block definitions and insertions exhaustively"""
        block_counts = Counter()
        
        # Count all block insertions
        for insert in self.msp.query('INSERT'):
            try:
                block_name = insert.dxf.name
                block_counts[block_name] += 1
            except:
                continue
        
        # Analyze each unique block
        for block_name, count in block_counts.items():
            try:
                block = self.doc.blocks.get(block_name)
                if block:
                    block_data = {
                        "name": block_name,
                        "count": count,
                        "entities": defaultdict(int),
                        "total_perimeter": 0.0,
                        "total_area": 0.0,
                        "material_hint": self._detect_material_from_name(block_name),
                        "attributes": []
                    }
                    
                    # Analyze block content
                    for entity in block:
                        etype = entity.dxftype()
                        block_data["entities"][etype] += 1
                        
                        if etype == 'LWPOLYLINE':
                            points = list(entity.get_points('xy'))
                            block_data["total_perimeter"] += self._calculate_perimeter(points, entity.closed)
                            if entity.closed:
                                block_data["total_area"] += abs(self._calculate_area(points))
                        elif etype == 'LINE':
                            length = math.sqrt(
                                (entity.dxf.end.x - entity.dxf.start.x)**2 +
                                (entity.dxf.end.y - entity.dxf.start.y)**2
                            )
                            block_data["total_perimeter"] += length
                        elif etype == 'CIRCLE':
                            block_data["total_perimeter"] += 2 * math.pi * entity.dxf.radius
                            block_data["total_area"] += math.pi * entity.dxf.radius**2
                        elif etype == 'ATTDEF':
                            block_data["attributes"].append({
                                "tag": entity.dxf.tag,
                                "default": entity.dxf.text
                            })
                    
                    block_data["entities"] = dict(block_data["entities"])
                    self.blocks_analyzed[block_name] = block_data
            except:
                continue
    
    def _should_skip_layer(self, layer_name: str) -> bool:
        """Check if layer should be skipped (non-structural)"""
        layer_lower = layer_name.lower()
        
        # Layer "0" is often used for auxiliary elements
        if layer_lower == '0':
            return True
        
        # Check against ignore patterns
        for pattern in self.IGNORE_LAYERS:
            if pattern in layer_lower:
                return True
        
        return False
    
    def _extract_all_geometry(self):
        """Extract structural geometry only (filtered)"""
        profile_count = 0
        
        # LWPOLYLINE
        for entity in self.msp.query('LWPOLYLINE'):
            if self._should_skip_layer(entity.dxf.layer):
                continue
            profile_count += 1
            profile = self._analyze_lwpolyline(entity, f"LWPOLY_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # POLYLINE
        for entity in self.msp.query('POLYLINE'):
            if self._should_skip_layer(entity.dxf.layer):
                continue
            profile_count += 1
            profile = self._analyze_polyline(entity, f"POLY_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # CIRCLE
        for entity in self.msp.query('CIRCLE'):
            if self._should_skip_layer(entity.dxf.layer):
                continue
            profile_count += 1
            self._process_circle(entity, profile_count)
        
        # ARC
        for entity in self.msp.query('ARC'):
            if self._should_skip_layer(entity.dxf.layer):
                continue
            profile_count += 1
            profile = self._analyze_arc(entity, f"ARC_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # ELLIPSE
        for entity in self.msp.query('ELLIPSE'):
            if self._should_skip_layer(entity.dxf.layer):
                continue
            profile_count += 1
            profile = self._analyze_ellipse(entity, f"ELLIPSE_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # LINE - Skip grouping lines as they're typically auxiliary/construction lines
        # Structural elements should be represented as polylines or blocks
        # Uncomment below if you need to process individual structural lines:
        # for entity in self.msp.query('LINE'):
        #     if self._should_skip_layer(entity.dxf.layer):
        #         continue
        #     ... process individual lines ...
        
        # SPLINE
        for entity in self.msp.query('SPLINE'):
            profile_count += 1
            profile = self._analyze_spline(entity, f"SPLINE_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # SOLID
        for entity in self.msp.query('SOLID'):
            profile_count += 1
            profile = self._analyze_solid(entity, f"SOLID_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # 3DFACE
        for entity in self.msp.query('3DFACE'):
            profile_count += 1
            profile = self._analyze_3dface(entity, f"3DFACE_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # HATCH
        for entity in self.msp.query('HATCH'):
            profile_count += 1
            profile = self._analyze_hatch(entity, f"HATCH_{profile_count:04d}")
            if profile:
                self.profiles.append(profile)
        
        # Update layer statistics
        for profile in self.profiles:
            layer = profile.layer
            if layer in self.layers_info:
                self.layers_info[layer]["profiles_count"] += 1
                self.layers_info[layer]["total_length_mm"] += profile.perimeter_mm * profile.quantity
    
    def _analyze_lwpolyline(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze a lightweight polyline"""
        try:
            points = list(entity.get_points('xy'))
            if len(points) < 2:
                return None
            
            is_closed = entity.closed
            perimeter = self._calculate_perimeter(points, is_closed)
            area_val = self._calculate_area(points) if is_closed else 0.0
            bbox = self._calculate_bounding_box(points)
            centroid = self._calculate_centroid(points)
            
            layer = entity.dxf.layer
            quantity = self._find_quantity_near_position(centroid)
            
            # Calculate length as max dimension
            length = max(bbox.get('width', 0), bbox.get('height', 0))
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=is_closed,
                perimeter_mm=perimeter,
                area_mm2=abs(area_val),
                length_mm=length,
                bounding_box=bbox,
                centroid=centroid,
                vertex_count=len(points),
                entity_type='LWPOLYLINE',
                color=getattr(entity.dxf, 'color', None),
                material_hint=self._detect_material_from_name(layer),
                quantity=quantity
            )
        except:
            return None
    
    def _analyze_polyline(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze a polyline"""
        try:
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if len(points) < 2:
                return None
            
            is_closed = entity.is_closed
            perimeter = self._calculate_perimeter(points, is_closed)
            area_val = self._calculate_area(points) if is_closed else 0.0
            bbox = self._calculate_bounding_box(points)
            centroid = self._calculate_centroid(points)
            layer = entity.dxf.layer
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=is_closed,
                perimeter_mm=perimeter,
                area_mm2=abs(area_val),
                length_mm=max(bbox.get('width', 0), bbox.get('height', 0)),
                bounding_box=bbox,
                centroid=centroid,
                vertex_count=len(points),
                entity_type='POLYLINE',
                material_hint=self._detect_material_from_name(layer),
                quantity=self._find_quantity_near_position(centroid)
            )
        except:
            return None
    
    def _process_circle(self, entity, count: int):
        """Process circle - classify as hole or profile"""
        try:
            radius = entity.dxf.radius
            center = (entity.dxf.center.x, entity.dxf.center.y)
            layer = entity.dxf.layer
            
            if radius < self.HOLE_RADIUS_THRESHOLD_MM:
                # It's a hole
                machining_time = 3.0 if radius < 5 else 5.0 if radius < 15 else 8.0
                self.features.append(GeometricFeature(
                    feature_type='hole',
                    position=center,
                    dimensions={'radius': radius, 'diameter': radius * 2},
                    layer=layer,
                    entity_type='CIRCLE',
                    machining_time_mins=machining_time
                ))
            else:
                # It's a profile
                self.profiles.append(ProfileData(
                    profile_id=f"CIRCLE_{count:04d}",
                    layer=layer,
                    is_closed=True,
                    perimeter_mm=2 * math.pi * radius,
                    area_mm2=math.pi * radius ** 2,
                    length_mm=radius * 2,
                    bounding_box={
                        'min_x': center[0] - radius, 'min_y': center[1] - radius,
                        'max_x': center[0] + radius, 'max_y': center[1] + radius,
                        'width': radius * 2, 'height': radius * 2
                    },
                    centroid=center,
                    vertex_count=1,
                    entity_type='CIRCLE',
                    material_hint=self._detect_material_from_name(layer),
                    quantity=self._find_quantity_near_position(center)
                ))
        except:
            pass
    
    def _analyze_arc(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze an arc"""
        try:
            radius = entity.dxf.radius
            center = (entity.dxf.center.x, entity.dxf.center.y)
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            
            angle_diff = end_angle - start_angle
            if angle_diff < 0:
                angle_diff += 2 * math.pi
            arc_length = radius * angle_diff
            
            layer = entity.dxf.layer
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=False,
                perimeter_mm=arc_length,
                area_mm2=0,
                length_mm=arc_length,
                bounding_box={
                    'min_x': center[0] - radius, 'min_y': center[1] - radius,
                    'max_x': center[0] + radius, 'max_y': center[1] + radius,
                    'width': radius * 2, 'height': radius * 2
                },
                centroid=center,
                vertex_count=2,
                entity_type='ARC',
                material_hint=self._detect_material_from_name(layer),
                quantity=1
            )
        except:
            return None
    
    def _analyze_ellipse(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze an ellipse"""
        try:
            center = (entity.dxf.center.x, entity.dxf.center.y)
            major_axis = entity.dxf.major_axis
            ratio = entity.dxf.ratio
            
            a = math.sqrt(major_axis.x**2 + major_axis.y**2)
            b = a * ratio
            
            # Ramanujan approximation
            h = ((a - b) ** 2) / ((a + b) ** 2)
            perimeter = math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
            area = math.pi * a * b
            
            layer = entity.dxf.layer
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=True,
                perimeter_mm=perimeter,
                area_mm2=area,
                length_mm=2 * a,
                bounding_box={
                    'min_x': center[0] - a, 'min_y': center[1] - b,
                    'max_x': center[0] + a, 'max_y': center[1] + b,
                    'width': 2 * a, 'height': 2 * b
                },
                centroid=center,
                vertex_count=1,
                entity_type='ELLIPSE',
                material_hint=self._detect_material_from_name(layer),
                quantity=1
            )
        except:
            return None
    
    def _analyze_spline(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze a spline"""
        try:
            control_points = list(entity.control_points)
            if len(control_points) < 2:
                return None
            
            points = [(p.x, p.y) for p in control_points]
            perimeter = self._calculate_perimeter(points, entity.closed)
            bbox = self._calculate_bounding_box(points)
            centroid = self._calculate_centroid(points)
            layer = entity.dxf.layer
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=entity.closed,
                perimeter_mm=perimeter,
                area_mm2=self._calculate_area(points) if entity.closed else 0,
                length_mm=perimeter,
                bounding_box=bbox,
                centroid=centroid,
                vertex_count=len(points),
                entity_type='SPLINE',
                material_hint=self._detect_material_from_name(layer),
                quantity=1
            )
        except:
            return None
    
    def _analyze_solid(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze a solid"""
        try:
            points = [
                (entity.dxf.vtx0.x, entity.dxf.vtx0.y),
                (entity.dxf.vtx1.x, entity.dxf.vtx1.y),
                (entity.dxf.vtx2.x, entity.dxf.vtx2.y),
                (entity.dxf.vtx3.x, entity.dxf.vtx3.y),
            ]
            
            perimeter = self._calculate_perimeter(points, True)
            area = abs(self._calculate_area(points))
            bbox = self._calculate_bounding_box(points)
            centroid = self._calculate_centroid(points)
            layer = entity.dxf.layer
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=True,
                perimeter_mm=perimeter,
                area_mm2=area,
                length_mm=max(bbox.get('width', 0), bbox.get('height', 0)),
                bounding_box=bbox,
                centroid=centroid,
                vertex_count=4,
                entity_type='SOLID',
                material_hint=self._detect_material_from_name(layer),
                quantity=1
            )
        except:
            return None
    
    def _analyze_3dface(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze a 3DFACE"""
        try:
            points = [
                (entity.dxf.vtx0.x, entity.dxf.vtx0.y),
                (entity.dxf.vtx1.x, entity.dxf.vtx1.y),
                (entity.dxf.vtx2.x, entity.dxf.vtx2.y),
                (entity.dxf.vtx3.x, entity.dxf.vtx3.y),
            ]
            
            perimeter = self._calculate_perimeter(points, True)
            area = abs(self._calculate_area(points))
            bbox = self._calculate_bounding_box(points)
            centroid = self._calculate_centroid(points)
            layer = entity.dxf.layer
            
            return ProfileData(
                profile_id=profile_id,
                layer=layer,
                is_closed=True,
                perimeter_mm=perimeter,
                area_mm2=area,
                length_mm=max(bbox.get('width', 0), bbox.get('height', 0)),
                bounding_box=bbox,
                centroid=centroid,
                vertex_count=4,
                entity_type='3DFACE',
                material_hint=self._detect_material_from_name(layer),
                quantity=1
            )
        except:
            return None
    
    def _analyze_hatch(self, entity, profile_id: str) -> Optional[ProfileData]:
        """Analyze a hatch"""
        try:
            layer = entity.dxf.layer
            total_area = 0
            total_perimeter = 0
            all_points = []
            
            for path in entity.paths:
                if hasattr(path, 'vertices'):
                    points = [(v.x, v.y) for v in path.vertices]
                    if points:
                        all_points.extend(points)
                        total_perimeter += self._calculate_perimeter(points, True)
                        total_area += abs(self._calculate_area(points))
            
            if all_points:
                bbox = self._calculate_bounding_box(all_points)
                centroid = self._calculate_centroid(all_points)
                
                return ProfileData(
                    profile_id=profile_id,
                    layer=layer,
                    is_closed=True,
                    perimeter_mm=total_perimeter,
                    area_mm2=total_area,
                    length_mm=max(bbox.get('width', 0), bbox.get('height', 0)),
                    bounding_box=bbox,
                    centroid=centroid,
                    vertex_count=len(all_points),
                    entity_type='HATCH',
                    material_hint=self._detect_material_from_name(layer),
                    quantity=1
                )
        except:
            return None
    
    def _find_quantity_near_position(self, position: Tuple[float, float], radius: float = 50) -> int:
        """Find quantity hint from nearby text entities
        
        NOTA: Para desenhos estruturais, quantidades são raramente anotadas próximo
        aos elementos. É mais seguro assumir qty=1 e deixar o utilizador ajustar.
        Desativado por defeito para evitar falsos positivos.
        """
        # Desativado - retorna sempre 1 para evitar falsos positivos
        # A maioria das "quantidades" detectadas são na verdade dimensões (50x20, 100mm, etc.)
        return 1
        
        # Código original comentado para referência:
        # for text in self.texts_extracted:
        #     qty = text.get('quantity_hint')
        #     if qty and 1 < qty <= 100:
        #         content = text.get('content', '').upper()
        #         if any(marker in content for marker in ['UN', 'PC', 'QTY', 'QUANT']):
        #             text_pos = text.get('position', (0, 0))
        #             dist = math.sqrt((position[0] - text_pos[0])**2 + (position[1] - text_pos[1])**2)
        #             if dist < radius:
        #                 return qty
        # return 1
    
    def _detect_all_features(self):
        """Detect all machining features"""
        for profile in self.profiles:
            # Complex profiles have notches
            if profile.vertex_count > 8:
                notch_prob = min(1.0, (profile.vertex_count - 4) / 20)
                if notch_prob > 0.3:
                    self.features.append(GeometricFeature(
                        feature_type='notch',
                        position=profile.centroid,
                        dimensions={'complexity': profile.vertex_count},
                        layer=profile.layer,
                        entity_type=profile.entity_type,
                        machining_time_mins=8.0 * notch_prob
                    ))
            
            # Detect slots
            bbox = profile.bounding_box
            if bbox['width'] > 0 and bbox['height'] > 0:
                aspect = max(bbox['width'], bbox['height']) / min(bbox['width'], bbox['height'])
                if aspect > 5 and min(bbox['width'], bbox['height']) < 20:
                    self.features.append(GeometricFeature(
                        feature_type='slot',
                        position=profile.centroid,
                        dimensions={
                            'width': min(bbox['width'], bbox['height']),
                            'length': max(bbox['width'], bbox['height'])
                        },
                        layer=profile.layer,
                        entity_type=profile.entity_type,
                        machining_time_mins=6.0
                    ))
    
    def _calculate_complexity(self):
        """Calculate complexity score for each profile"""
        for profile in self.profiles:
            vertex_factor = 1.0 + (profile.vertex_count - 4) * 0.05
            vertex_factor = max(1.0, min(vertex_factor, 2.0))
            
            # Count features near this profile
            profile_features = [f for f in self.features 
                              if f.layer == profile.layer or 
                              (abs(f.position[0] - profile.centroid[0]) < 100 and 
                               abs(f.position[1] - profile.centroid[1]) < 100)]
            feature_factor = 1.0 + len(profile_features) * 0.15
            
            bbox = profile.bounding_box
            if bbox['height'] > 0 and bbox['width'] > 0:
                aspect = max(bbox['width'], bbox['height']) / min(bbox['width'], bbox['height'])
                aspect_factor = 1.0 + (aspect - 1) * 0.03
                aspect_factor = min(aspect_factor, 1.3)
            else:
                aspect_factor = 1.0
            
            profile.complexity_score = min(3.0, vertex_factor * feature_factor * aspect_factor)
            profile.features = profile_features
    
    def _compile_material_quantities(self):
        """Compile material quantities from all sources"""
        # From blocks
        for block_name, block_data in self.blocks_analyzed.items():
            if block_data['count'] > 0 and block_data['total_perimeter'] > 0:
                self.material_quantities.append(MaterialQuantity(
                    material_type=block_data.get('material_hint', 'aluminio') or 'aluminio',
                    profile_reference=block_name,
                    description=f"Bloco: {block_name}",
                    quantity=block_data['count'],
                    unit_length_mm=block_data['total_perimeter'],
                    total_length_mm=block_data['total_perimeter'] * block_data['count'],
                    unit_weight_kg=0,
                    total_weight_kg=0,
                    unit_area_mm2=block_data['total_area'],
                    total_area_mm2=block_data['total_area'] * block_data['count'],
                    layer='BLOCKS',
                    source='block_count'
                ))
        
        # From layers
        layer_aggregates = defaultdict(lambda: {
            'count': 0, 'total_perimeter': 0, 'total_area': 0, 
            'total_quantity': 0, 'material': None
        })
        
        for profile in self.profiles:
            layer = profile.layer
            layer_aggregates[layer]['count'] += 1
            layer_aggregates[layer]['total_perimeter'] += profile.perimeter_mm * profile.quantity
            layer_aggregates[layer]['total_area'] += profile.area_mm2 * profile.quantity
            layer_aggregates[layer]['total_quantity'] += profile.quantity
            if profile.material_hint:
                layer_aggregates[layer]['material'] = profile.material_hint
        
        for layer, data in layer_aggregates.items():
            if data['total_perimeter'] > 0:
                material = data['material'] or self._detect_material_from_name(layer) or 'aluminio'
                avg_perimeter = data['total_perimeter'] / max(data['count'], 1)
                
                self.material_quantities.append(MaterialQuantity(
                    material_type=material,
                    profile_reference=layer,
                    description=f"Layer: {layer} ({data['count']} perfis)",
                    quantity=data['total_quantity'],
                    unit_length_mm=avg_perimeter,
                    total_length_mm=data['total_perimeter'],
                    unit_weight_kg=0,
                    total_weight_kg=0,
                    unit_area_mm2=data['total_area'] / max(data['count'], 1),
                    total_area_mm2=data['total_area'],
                    layer=layer,
                    source='layer_analysis'
                ))
    
    def _apply_scale_corrections(self):
        """Apply unit conversion to measurements (convert to mm)
        
        Heurística inteligente:
        - Se unidades são 'm' e valores típicos < 100, converter para mm (factor 1000)
        - Se unidades são 'm' mas valores típicos > 500, assumir que já está em mm
        - Perfis estruturais típicos: 0.5m - 15m (500mm - 15000mm)
        """
        factor = self.scale_info.unit_factor
        units = self.scale_info.units
        
        if factor == 1.0:
            return
        
        # Analisar amostra de valores para decidir
        if self.profiles:
            sample_lengths = [p.length_mm for p in self.profiles[:50] if p.length_mm > 0]
            if sample_lengths:
                avg_length = sum(sample_lengths) / len(sample_lengths)
                max_length = max(sample_lengths)
                
                # Se unidade é metros e valores médios < 100
                # (típico para desenhos em metros: vigas de 0.5 a 20m)
                if units == 'm' and avg_length < 100:
                    # Aplicar conversão - valores estão em metros
                    pass  # Continuar com a conversão
                elif max_length > 1000:
                    # Valores já parecem estar em mm (> 1 metro)
                    self.scale_info.unit_factor = 1.0
                    return
        
        # Aplicar conversão
        for profile in self.profiles:
            profile.perimeter_mm *= factor
            profile.area_mm2 *= (factor ** 2)
            profile.length_mm *= factor
            profile.bounding_box = {
                'min_x': profile.bounding_box['min_x'] * factor,
                'min_y': profile.bounding_box['min_y'] * factor,
                'max_x': profile.bounding_box['max_x'] * factor,
                'max_y': profile.bounding_box['max_y'] * factor,
                'width': profile.bounding_box['width'] * factor,
                'height': profile.bounding_box['height'] * factor,
            }
        
        for mq in self.material_quantities:
            mq.unit_length_mm *= factor
            mq.total_length_mm *= factor
            mq.unit_area_mm2 *= (factor ** 2)
            mq.total_area_mm2 *= (factor ** 2)
    
    @staticmethod
    def _calculate_perimeter(points: List[Tuple[float, float]], is_closed: bool) -> float:
        if not points or len(points) < 2:
            return 0.0
        perimeter = 0.0
        n = len(points)
        for i in range(n - 1):
            dx = points[i+1][0] - points[i][0]
            dy = points[i+1][1] - points[i][1]
            perimeter += math.sqrt(dx*dx + dy*dy)
        if is_closed and n > 1:
            dx = points[0][0] - points[-1][0]
            dy = points[0][1] - points[-1][1]
            perimeter += math.sqrt(dx*dx + dy*dy)
        return perimeter
    
    @staticmethod
    def _calculate_area(points: List[Tuple[float, float]]) -> float:
        n = len(points)
        if n < 3:
            return 0.0
        area_val = 0.0
        for i in range(n):
            j = (i + 1) % n
            area_val += points[i][0] * points[j][1]
            area_val -= points[j][0] * points[i][1]
        return abs(area_val) / 2.0
    
    @staticmethod
    def _calculate_bounding_box(points: List[Tuple[float, float]]) -> Dict[str, float]:
        if not points:
            return {'min_x': 0, 'min_y': 0, 'max_x': 0, 'max_y': 0, 'width': 0, 'height': 0}
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        min_x, max_x = min(x_coords), max(x_coords)
        min_y, max_y = min(y_coords), max(y_coords)
        return {
            'min_x': round(min_x, 2), 'min_y': round(min_y, 2),
            'max_x': round(max_x, 2), 'max_y': round(max_y, 2),
            'width': round(max_x - min_x, 2), 'height': round(max_y - min_y, 2)
        }
    
    @staticmethod
    def _calculate_centroid(points: List[Tuple[float, float]]) -> Tuple[float, float]:
        if not points:
            return (0.0, 0.0)
        x_sum = sum(p[0] for p in points)
        y_sum = sum(p[1] for p in points)
        n = len(points)
        return (round(x_sum / n, 2), round(y_sum / n, 2))
    
    def _get_features_summary(self) -> Dict[str, int]:
        summary = {}
        for feature in self.features:
            ft = feature.feature_type
            summary[ft] = summary.get(ft, 0) + 1
        return summary
    
    def get_svg_preview(self, width: int = 800, height: int = 600) -> str:
        if not self.profiles and not self.features:
            return '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        
        all_points = []
        for p in self.profiles:
            bb = p.bounding_box
            all_points.extend([(bb['min_x'], bb['min_y']), (bb['max_x'], bb['max_y'])])
        
        if not all_points:
            return '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        
        min_x = min(p[0] for p in all_points) - 10
        min_y = min(p[1] for p in all_points) - 10
        max_x = max(p[0] for p in all_points) + 10
        max_y = max(p[1] for p in all_points) + 10
        
        view_width = max_x - min_x
        view_height = max_y - min_y
        
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {min_y} {view_width} {view_height}" '
            f'width="{width}" height="{height}" style="background:#1e293b">'
        ]
        
        colors = {
            'LWPOLYLINE': '#38bdf8', 'POLYLINE': '#38bdf8', 'CIRCLE': '#22d3ee',
            'ARC': '#a78bfa', 'ELLIPSE': '#f472b6', 'LINE_GROUP': '#fbbf24',
            'SPLINE': '#34d399', 'SOLID': '#f97316', '3DFACE': '#f97316',
            'HATCH': '#6366f1'
        }
        
        for p in self.profiles:
            bb = p.bounding_box
            color = colors.get(p.entity_type, '#38bdf8')
            svg_parts.append(
                f'<rect x="{bb["min_x"]}" y="{bb["min_y"]}" '
                f'width="{bb["width"]}" height="{bb["height"]}" '
                f'fill="none" stroke="{color}" stroke-width="1" opacity="0.8"/>'
            )
        
        for f in self.features:
            if f.feature_type == 'hole':
                svg_parts.append(
                    f'<circle cx="{f.position[0]}" cy="{f.position[1]}" '
                    f'r="{f.dimensions.get("radius", 5)}" fill="#10b981" opacity="0.5"/>'
                )
        
        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)


def parse_dxf_file(file_path: str) -> Dict[str, Any]:
    parser = DXFParser(file_path)
    return parser.parse()
