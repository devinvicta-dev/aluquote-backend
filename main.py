"""
AluQuote AI - FastAPI Backend - ENHANCED VERSION
Main API server for aluminum facade budgeting automation
Suporta múltiplos ficheiros DXF e PDF com análise exaustiva
"""

import os
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import io
from pydantic import BaseModel

from dxf_parser import DXFParser, parse_dxf_file
from pdf_reader import PDFReader, parse_pdf_file
from budget_calculator import (
    BudgetCalculator, PricingParameters, calculate_quick_estimate, 
    BudgetCategory, MaterialDatabase, get_available_materials
)
from excel_parser import FLYSTEELExcelParser, extract_steel_quantities_from_excel

# Import drawing extractor for PDF/DXF analysis
try:
    from drawing_extractor import (
        extract_quantities_from_drawings, 
        identify_drawing_pdfs,
        DrawingExtractionResult
    )
    HAS_DRAWING_EXTRACTOR = True
except ImportError:
    HAS_DRAWING_EXTRACTOR = False

# Import cost database
try:
    from cost_database import cost_db, CostDatabase
    HAS_COST_DB = True
except ImportError:
    HAS_COST_DB = False
    cost_db = None

# Configuration
UPLOAD_DIR = Path("./uploads")
EXPORT_DIR = Path("./exports")
UPLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

# Initialize FastAPI
app = FastAPI(
    title="AluQuote AI",
    description="AI-powered aluminum facade budgeting automation - Enhanced",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage
projects_db = {}
files_db = {}

# Drawing file patterns for classification
DRAWING_PATTERNS = ['des', 'desenho', 'drawing', 'planta', 'corte', 'estrutura', 
                    'montagem', 'caleiro', 'painel', 'revestimento', 'madres', 
                    'pala', 'cobertura', 'fachada', 'madre']
PROPOSAL_PATTERNS = ['proposta', 'orçamento', 'orcamento', 'quote', 'proposal', 'budget']


# ============== Pydantic Models ==============

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class PricingParametersUpdate(BaseModel):
    lme_price_usd_kg: Optional[float] = None
    lme_hedging_buffer_pct: Optional[float] = None
    labor_rate_eur_hr: Optional[float] = None
    base_waste_factor_pct: Optional[float] = None
    overhead_factor_pct: Optional[float] = None
    profit_margin_pct: Optional[float] = None

class BudgetRequest(BaseModel):
    project_id: str
    surface_treatment: str = "powder_coating_standard"
    parameters: Optional[PricingParametersUpdate] = None
    material_code: str = "S275"  # Material code (S275, AL6063, etc.)
    unit_multiplier: int = 1  # Number of identical units (e.g., 3 pavilions)
    auto_detect_multiplier: bool = True  # Auto-detect from PDF vs DXF comparison

class QuickEstimateRequest(BaseModel):
    weight_kg: float
    complexity: str = "medium"


# ============== Health Check ==============

@app.get("/")
async def root():
    return {
        "name": "AluQuote AI",
        "version": "2.0.0 - Enhanced",
        "status": "operational",
        "features": [
            "Extração exaustiva de DXF (escalas, geometrias, quantidades)",
            "Leitura detalhada de todos os PDFs",
            "Quantidades DXF prevalecem sobre PDF",
            "Correlação de especificações PDF com geometrias DXF"
        ],
        "endpoints": {
            "upload": "/api/upload",
            "projects": "/api/projects",
            "calculate": "/api/calculate",
            "export": "/api/export"
        }
    }

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ============== Cost Database Management ==============

@app.get("/api/costs/profiles")
async def list_steel_profiles():
    """List all available steel profiles with costs"""
    if not HAS_COST_DB or cost_db is None:
        raise HTTPException(status_code=503, detail="Cost database not available")
    
    profiles = cost_db.get_all_profiles()
    return {
        "success": True,
        "count": len(profiles),
        "profiles": [
            {
                "code": p.code,
                "designation": p.designation,
                "weight_per_meter": p.weight_per_meter,
                "area_per_meter": p.area_per_meter,
                "price_material": p.price_material,
                "price_fabrication": p.price_fabrication,
                "price_assembly": p.price_assembly,
                "price_painting_per_m2": p.price_painting,
                "price_lifting": p.price_lifting,
                "price_consumables": p.price_consumables,
                "price_transport": p.price_transport,
                "is_galvanized": p.is_galvanized
            }
            for p in profiles
        ]
    }

@app.get("/api/costs/cladding")
async def list_cladding_items():
    """List all available cladding items with costs"""
    if not HAS_COST_DB or cost_db is None:
        raise HTTPException(status_code=503, detail="Cost database not available")
    
    all_cladding = cost_db.get_all_cladding()
    
    def format_items(items):
        return [
            {
                "designation": item.designation,
                "unit": item.unit,
                "price_material": item.price_material,
                "price_fabrication": item.price_fabrication,
                "price_assembly": item.price_assembly,
                "price_painting": item.price_painting,
                "price_lifting": item.price_lifting,
                "price_consumables": item.price_consumables,
                "price_transport": item.price_transport,
                "total_price_per_unit": item.total_price_per_unit
            }
            for item in items
        ]
    
    return {
        "success": True,
        "facade": format_items(all_cladding["facade"]),
        "roof": format_items(all_cladding["roof"]),
        "accessories": format_items(all_cladding["accessories"])
    }

@app.post("/api/costs/calculate")
async def calculate_costs(items: List[Dict[str, Any]]):
    """
    Calculate costs for a list of items.
    Each item should have: {type: 'profile'|'cladding', name: str, quantity: float}
    """
    if not HAS_COST_DB or cost_db is None:
        raise HTTPException(status_code=503, detail="Cost database not available")
    
    results = []
    total_cost = 0
    total_weight = 0
    
    for item in items:
        item_type = item.get("type", "profile")
        name = item.get("name", "")
        quantity = float(item.get("quantity", 0))
        
        if item_type == "profile":
            profile = cost_db.find_profile(name)
            if profile and quantity > 0:
                cost_data = profile.calculate_cost(quantity)
                results.append({
                    "type": "profile",
                    "name": profile.designation,
                    "quantity": quantity,
                    "unit": "m",
                    "weight_kg": cost_data["weight_kg"],
                    "cost_breakdown": {
                        "material": cost_data["cost_material"],
                        "fabrication": cost_data["cost_fabrication"],
                        "assembly": cost_data["cost_assembly"],
                        "painting": cost_data["cost_painting"],
                        "lifting": cost_data["cost_lifting"],
                        "consumables": cost_data["cost_consumables"],
                        "transport": cost_data["cost_transport"]
                    },
                    "total_cost": cost_data["total_cost"]
                })
                total_cost += cost_data["total_cost"]
                total_weight += cost_data["weight_kg"]
        else:
            cladding = cost_db.find_cladding(name)
            if cladding and quantity > 0:
                cost_data = cladding.calculate_cost(quantity)
                results.append({
                    "type": "cladding",
                    "name": cladding.designation,
                    "quantity": quantity,
                    "unit": cladding.unit,
                    "cost_breakdown": {
                        "material": cost_data["cost_material"],
                        "fabrication": cost_data["cost_fabrication"],
                        "assembly": cost_data["cost_assembly"],
                        "painting": cost_data["cost_painting"],
                        "lifting": cost_data["cost_lifting"],
                        "consumables": cost_data["cost_consumables"],
                        "transport": cost_data["cost_transport"]
                    },
                    "total_cost": cost_data["total_cost"]
                })
                total_cost += cost_data["total_cost"]
    
    return {
        "success": True,
        "items": results,
        "summary": {
            "total_items": len(results),
            "total_weight_kg": total_weight,
            "total_cost": total_cost
        }
    }

@app.get("/api/costs/search/{search_term}")
async def search_costs(search_term: str):
    """Search for profiles or cladding items by name"""
    if not HAS_COST_DB or cost_db is None:
        raise HTTPException(status_code=503, detail="Cost database not available")
    
    results = []
    
    # Search profiles
    profile = cost_db.find_profile(search_term)
    if profile:
        results.append({
            "type": "profile",
            "designation": profile.designation,
            "weight_per_meter": profile.weight_per_meter,
            "area_per_meter": profile.area_per_meter
        })
    
    # Search cladding
    cladding = cost_db.find_cladding(search_term)
    if cladding:
        results.append({
            "type": "cladding",
            "designation": cladding.designation,
            "unit": cladding.unit,
            "total_price_per_unit": cladding.total_price_per_unit
        })
    
    return {
        "success": True,
        "search_term": search_term,
        "results": results
    }


# ============== Project Management ==============

@app.post("/api/projects")
async def create_project(project: ProjectCreate):
    """Create a new budgeting project"""
    project_id = str(uuid.uuid4())[:8]
    
    projects_db[project_id] = {
        "id": project_id,
        "name": project.name,
        "description": project.description,
        "created_at": datetime.now().isoformat(),
        "files": [],
        "dxf_analyses": [],  # Multiple DXF files
        "pdf_analyses": [],  # Multiple PDF files (proposals)
        "pdf_drawings": [],  # PDF technical drawings
        "excel_analyses": [],  # FLYSTEEL Excel cost structure files
        "merged_dxf_analysis": None,
        "merged_pdf_analysis": None,
        "drawing_extraction": None,  # Results from drawing analysis
        "budget": None,
        "status": "created"
    }
    
    return projects_db[project_id]

@app.get("/api/projects")
async def list_projects():
    """List all projects"""
    return list(projects_db.values())

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get project details"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects_db[project_id]

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    del projects_db[project_id]
    return {"message": "Project deleted", "id": project_id}


# ============== File Upload & Processing ==============

@app.post("/api/upload")
async def upload_files(
    project_id: str = Form(...),
    files: List[UploadFile] = File(...)
):
    """
    Upload and process MULTIPLE DXF and PDF files
    Analyzes each file exhaustively
    """
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    results = []
    
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        file_ext = Path(file.filename).suffix.lower()
        
        # Validate file type
        if file_ext not in ['.dxf', '.pdf', '.dwg', '.xlsx', '.xls']:
            results.append({
                "filename": file.filename,
                "status": "rejected",
                "error": "Tipo de ficheiro não suportado. Apenas .dxf, .dwg, .pdf e .xlsx são aceites."
            })
            continue
        
        # Handle DWG files (AutoCAD native format)
        if file_ext == '.dwg':
            results.append({
                "file_id": file_id,
                "filename": file.filename,
                "type": "dwg",
                "category": "cad_drawing",
                "status": "needs_conversion",
                "error": None,
                "message": "Ficheiro DWG detectado. Para melhor compatibilidade, converta para DXF no AutoCAD (Guardar Como > DXF). A análise será mais precisa com ficheiros DXF.",
                "analysis_summary": {
                    "total_items": 0,
                    "note": "Conversão DWG→DXF recomendada"
                }
            })
            continue
        
        # Save file
        file_path = UPLOAD_DIR / f"{file_id}_{file.filename}"
        
        try:
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            
            # Process based on file type
            if file_ext == '.dxf':
                analysis = process_dxf_exhaustive(str(file_path))
                file_type = "dxf"
                category = categorize_dxf(analysis)
                project["dxf_analyses"].append(analysis)
            elif file_ext in ['.xlsx', '.xls']:
                analysis = process_excel_flysteel(str(file_path))
                file_type = "excel"
                category = "cost_structure"
                if "excel_analyses" not in project:
                    project["excel_analyses"] = []
                project["excel_analyses"].append(analysis)
            else:
                # Classify PDF: drawing vs proposal
                filename_lower = file.filename.lower()
                is_drawing = any(pattern in filename_lower for pattern in DRAWING_PATTERNS)
                is_proposal = any(pattern in filename_lower for pattern in PROPOSAL_PATTERNS)
                
                # If it starts with "DES" or has a number prefix, treat as drawing
                if not is_proposal and (filename_lower.startswith('des') or 
                                        (len(filename_lower) > 0 and filename_lower[0].isdigit())):
                    is_drawing = True
                
                analysis = process_pdf_exhaustive(str(file_path))
                file_type = "pdf"
                
                if is_drawing and not is_proposal:
                    # Technical drawing PDF
                    category = "technical_drawing"
                    if "pdf_drawings" not in project:
                        project["pdf_drawings"] = []
                    project["pdf_drawings"].append({
                        "path": str(file_path),
                        "filename": file.filename,
                        "analysis": analysis
                    })
                else:
                    # Proposal/commercial PDF
                    category = categorize_pdf(analysis)
                    project["pdf_analyses"].append(analysis)
            
            # Store file info
            file_info = {
                "id": file_id,
                "filename": file.filename,
                "type": file_type,
                "category": category,
                "path": str(file_path),
                "size_bytes": len(content),
                "uploaded_at": datetime.now().isoformat(),
                "analysis_success": analysis.get("success", False),
                "analysis": analysis
            }
            
            files_db[file_id] = file_info
            project["files"].append(file_info)
            
            results.append({
                "file_id": file_id,
                "filename": file.filename,
                "type": file_type,
                "category": category,
                "status": "processed" if analysis.get("success") else "error",
                "analysis_summary": get_analysis_summary(analysis, file_type),
                "error": analysis.get("error") if not analysis.get("success") else None
            })
            
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e)
            })
    
    # Merge analyses after all files are processed
    merge_project_analyses(project)
    
    project["status"] = "files_uploaded"
    
    # Process drawing PDFs if extractor available
    if HAS_DRAWING_EXTRACTOR and project.get("pdf_drawings"):
        try:
            drawing_paths = [d["path"] for d in project["pdf_drawings"]]
            drawing_result = extract_quantities_from_drawings(
                pdf_paths=drawing_paths,
                dxf_data=project.get("dxf_analyses", [])
            )
            project["drawing_extraction"] = drawing_result
        except Exception as e:
            print(f"[DrawingExtractor] Erro: {str(e)}")
    
    return {
        "project_id": project_id,
        "files_processed": len(results),
        "dxf_files": len(project["dxf_analyses"]),
        "pdf_files": len(project["pdf_analyses"]),
        "pdf_drawings": len(project.get("pdf_drawings", [])),
        "results": results,
        "drawing_extraction_available": project.get("drawing_extraction") is not None
    }


def process_dxf_exhaustive(file_path: str) -> dict:
    """Process DXF file with exhaustive extraction"""
    parser = DXFParser(file_path)
    result = parser.parse()
    return result


def process_pdf_exhaustive(file_path: str) -> dict:
    """Process PDF file with exhaustive extraction"""
    reader = PDFReader(file_path)
    result = reader.parse()
    return result


def process_excel_flysteel(file_path: str) -> dict:
    """
    Process FLYSTEEL Excel cost structure file.
    Extracts accurate steel quantities with 95%+ confidence.
    """
    try:
        result = extract_steel_quantities_from_excel(file_path)
        result["file_path"] = file_path
        result["file_type"] = "excel_flysteel"
        return result
    except Exception as e:
        return {
            "success": False,
            "file_path": file_path,
            "file_type": "excel_flysteel",
            "error": str(e),
            "profiles": [],
            "summary": {
                "estrutura_metalica_kg": 0,
                "madres_galvanizadas_kg": 0,
                "outros_kg": 0,
                "total_geral_kg": 0
            },
            "confidence": 0
        }


def merge_project_analyses(project: Dict):
    """Merge multiple DXF and PDF analyses into unified views"""
    
    # Merge DXF analyses
    if project["dxf_analyses"]:
        merged_dxf = {
            "success": True,
            "profiles": [],
            "features_summary": {},
            "material_quantities": [],
            "texts_extracted": [],
            "layers": {},
            "blocks_analyzed": {},
            "total_profiles": 0,
            "total_features": 0,
            "files_merged": len(project["dxf_analyses"])
        }
        
        for analysis in project["dxf_analyses"]:
            if analysis.get("success"):
                # Merge profiles
                for profile in analysis.get("profiles", []):
                    profile["source_file"] = analysis.get("file_info", {}).get("filename", "")
                    merged_dxf["profiles"].append(profile)
                
                # Merge features
                for ftype, count in analysis.get("features_summary", {}).items():
                    merged_dxf["features_summary"][ftype] = merged_dxf["features_summary"].get(ftype, 0) + count
                
                # Merge material quantities
                merged_dxf["material_quantities"].extend(analysis.get("material_quantities", []))
                
                # Merge texts
                merged_dxf["texts_extracted"].extend(analysis.get("texts_extracted", []))
                
                # Merge layers
                merged_dxf["layers"].update(analysis.get("layers", {}))
                
                # Merge blocks
                merged_dxf["blocks_analyzed"].update(analysis.get("blocks_analyzed", {}))
        
        merged_dxf["total_profiles"] = len(merged_dxf["profiles"])
        merged_dxf["total_features"] = sum(merged_dxf["features_summary"].values())
        
        project["merged_dxf_analysis"] = merged_dxf
    
    # Merge PDF analyses
    if project["pdf_analyses"]:
        merged_pdf = {
            "success": True,
            "bom_items": [],
            "constraints": [],
            "dimension_specs": [],
            "material_specs": [],
            "profile_references": [],
            "total_items": 0,
            "total_constraints": 0,
            "files_merged": len(project["pdf_analyses"])
        }
        
        for analysis in project["pdf_analyses"]:
            if analysis.get("success"):
                # Merge BOM items
                for item in analysis.get("bom_items", []):
                    item["source_file"] = analysis.get("document_info", {}).get("filename", "")
                    merged_pdf["bom_items"].append(item)
                
                # Merge constraints
                for constraint in analysis.get("constraints", []):
                    constraint["source_file"] = analysis.get("document_info", {}).get("filename", "")
                    merged_pdf["constraints"].append(constraint)
                
                # Merge specs
                merged_pdf["dimension_specs"].extend(analysis.get("dimension_specs", []))
                merged_pdf["material_specs"].extend(analysis.get("material_specs", []))
                merged_pdf["profile_references"].extend(analysis.get("profile_references", []))
        
        # Deduplicate profile references
        merged_pdf["profile_references"] = list(set(merged_pdf["profile_references"]))
        
        merged_pdf["total_items"] = len(merged_pdf["bom_items"])
        merged_pdf["total_constraints"] = len(merged_pdf["constraints"])
        
        project["merged_pdf_analysis"] = merged_pdf


def categorize_dxf(analysis: dict) -> str:
    """Categorize DXF file based on content"""
    if not analysis.get("success"):
        return "error"
    
    stats = analysis.get("statistics", {})
    profiles = stats.get("total_profiles", 0)
    features = stats.get("total_features", 0)
    texts = stats.get("total_texts", 0)
    
    if profiles > 50:
        return "floor_plan"
    elif features > 10:
        return "machining_detail"
    elif texts > 20:
        return "annotated_drawing"
    elif profiles > 0:
        return "profile_detail"
    return "general_drawing"


def categorize_pdf(analysis: dict) -> str:
    """Categorize PDF file based on content"""
    if not analysis.get("success"):
        return "error"
    
    stats = analysis.get("statistics", {})
    bom_items = stats.get("total_items", 0)
    constraints = stats.get("total_constraints", 0)
    
    if bom_items > 5:
        return "bill_of_materials"
    elif constraints > 10:
        return "technical_specification"
    elif bom_items > 0:
        return "partial_bom"
    return "general_document"


def get_analysis_summary(analysis: dict, file_type: str) -> dict:
    """Get brief summary of analysis results"""
    if not analysis.get("success"):
        return {"error": analysis.get("error", "Análise falhou")}
    
    if file_type == "dxf":
        stats = analysis.get("statistics", {})
        return {
            "total_profiles": stats.get("total_profiles", 0),
            "total_features": stats.get("total_features", 0),
            "total_material_items": stats.get("total_material_items", 0),
            "estimated_weight_kg": stats.get("estimated_weight_kg", 0),
            "total_perimeter_mm": stats.get("total_perimeter_mm", 0),
            "total_length_mm": stats.get("total_length_mm", 0),
            "unique_layers": stats.get("unique_layers", 0),
            "total_texts": stats.get("total_texts", 0),
            "scale": analysis.get("scale_info", {}).get("drawing_scale", 1.0),
            "units": analysis.get("scale_info", {}).get("units", "mm")
        }
    else:
        stats = analysis.get("statistics", {})
        return {
            "total_items": stats.get("total_items", 0),
            "total_quantity": stats.get("total_quantity", 0),
            "unique_references": stats.get("unique_references", 0),
            "total_constraints": stats.get("total_constraints", 0),
            "pages_analyzed": analysis.get("document_info", {}).get("total_pages", 0),
            "dimension_specs_found": len(analysis.get("dimension_specs", [])),
            "material_specs_found": len(analysis.get("material_specs", []))
        }


# ============== Analysis Endpoints ==============

@app.get("/api/projects/{project_id}/dxf-analysis")
async def get_dxf_analysis(project_id: str):
    """Get merged DXF analysis for a project"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    
    if project["merged_dxf_analysis"]:
        return project["merged_dxf_analysis"]
    elif project["dxf_analyses"]:
        return project["dxf_analyses"][0]
    else:
        raise HTTPException(status_code=404, detail="Nenhuma análise DXF disponível")


@app.get("/api/projects/{project_id}/pdf-analysis")
async def get_pdf_analysis(project_id: str):
    """Get merged PDF analysis for a project"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    
    if project["merged_pdf_analysis"]:
        return project["merged_pdf_analysis"]
    elif project["pdf_analyses"]:
        return project["pdf_analyses"][0]
    else:
        raise HTTPException(status_code=404, detail="Nenhuma análise PDF disponível")


@app.get("/api/projects/{project_id}/all-analyses")
async def get_all_analyses(project_id: str):
    """Get all individual analyses for a project"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    
    return {
        "dxf_analyses": project["dxf_analyses"],
        "pdf_analyses": project["pdf_analyses"],
        "merged_dxf": project["merged_dxf_analysis"],
        "merged_pdf": project["merged_pdf_analysis"],
        "files_count": {
            "dxf": len(project["dxf_analyses"]),
            "pdf": len(project["pdf_analyses"])
        }
    }


@app.get("/api/projects/{project_id}/dxf-preview")
async def get_dxf_preview(project_id: str):
    """Get SVG preview of DXF file"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    dxf_files = [f for f in project.get("files", []) if f["type"] == "dxf"]
    
    if not dxf_files:
        raise HTTPException(status_code=404, detail="Nenhum ficheiro DXF no projeto")
    
    # Generate SVG preview from first DXF
    parser = DXFParser(dxf_files[0]["path"])
    parser.parse()
    svg = parser.get_svg_preview()
    
    return {"svg": svg, "file": dxf_files[0]["filename"]}


@app.get("/api/projects/{project_id}/drawing-analysis")
async def get_drawing_analysis(project_id: str):
    """
    Get drawing extraction results and discrepancy alerts.
    Shows items found in PDF drawings/DXF that are missing from Excel.
    """
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    drawing_extraction = project.get("drawing_extraction")
    
    if not drawing_extraction:
        return {
            "success": False,
            "message": "Nenhuma análise de desenhos disponível. Carregue PDFs de desenhos técnicos.",
            "pdf_drawings_count": len(project.get("pdf_drawings", [])),
            "has_excel_data": bool(project.get("excel_analyses"))
        }
    
    return {
        "success": True,
        "drawing_extraction": drawing_extraction,
        "pdf_drawings": [
            {"filename": d.get("filename"), "path": d.get("path")} 
            for d in project.get("pdf_drawings", [])
        ],
        "discrepancy_summary": {
            "total_alerts": len(drawing_extraction.get("discrepancy_alerts", [])),
            "missing_in_excel": len([
                a for a in drawing_extraction.get("discrepancy_alerts", [])
                if a.get("alert_type") == "missing_in_excel"
            ]),
            "value_mismatches": len([
                a for a in drawing_extraction.get("discrepancy_alerts", [])
                if a.get("alert_type") == "value_mismatch"
            ])
        }
    }


# ============== Budget Calculation ==============

@app.post("/api/calculate")
async def calculate_budget(request: BudgetRequest):
    """
    Calculate complete budget based on uploaded files
    REGRA DE PRIORIDADE:
    1. Excel FLYSTEEL (95%+ precisão)
    2. DXF (estimativa geométrica)
    3. PDF (extração de texto)
    """
    if request.project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[request.project_id]
    
    # Check for Excel analyses (highest priority - 95%+ accuracy)
    excel_analyses = project.get("excel_analyses", [])
    has_excel = any(e.get("success", False) for e in excel_analyses)
    excel_data = None
    
    if has_excel:
        # Use merge_excel_extractions for proper duplicate detection
        from excel_parser import merge_excel_extractions
        
        merged_excel = merge_excel_extractions(excel_analyses)
        
        if merged_excel.get("success"):
            summary = merged_excel.get("summary", {})
            excel_data = {
                "success": True,
                "estrutura_metalica_kg": summary.get("estrutura_metalica_kg", 0),
                "madres_galvanizadas_kg": summary.get("madres_galvanizadas_kg", 0),  # Includes OMEGA
                "omega_kg": summary.get("omega_kg", 0),
                "outros_kg": summary.get("outros_kg", 0),
                "total_geral_kg": summary.get("total_geral_kg", 0),
                "profiles": merged_excel.get("profiles", []),
                "confidence": merged_excel.get("confidence", 0.90),
                "source": "excel_flysteel_merged",
                "duplicate_warnings": merged_excel.get("duplicate_warnings", []),
                "requires_validation": merged_excel.get("requires_user_validation", False),
                # REVESTIMENTOS - cobertura, fachada, divisórias, caleiros
                "revestimentos": merged_excel.get("revestimentos", [])
            }
        else:
            # Fallback to simple merge
            excel_data = {
                "success": True,
                "estrutura_metalica_kg": 0,
                "madres_galvanizadas_kg": 0,
                "omega_kg": 0,
                "outros_kg": 0,
                "total_geral_kg": 0,
                "profiles": [],
                "revestimentos": [],  # Added revestimentos
                "confidence": 0,
                "source": "excel_flysteel"
            }
            for e in excel_analyses:
                if e.get("success"):
                    summary = e.get("summary", {})
                    excel_data["estrutura_metalica_kg"] += summary.get("estrutura_metalica_kg", 0)
                    excel_data["madres_galvanizadas_kg"] += summary.get("madres_galvanizadas_kg", 0)
                    excel_data["omega_kg"] += summary.get("omega_kg", 0)
                    excel_data["outros_kg"] += summary.get("outros_kg", 0)
                    excel_data["total_geral_kg"] += summary.get("total_geral_kg", 0)
                    excel_data["profiles"].extend(e.get("profiles", []))
                    excel_data["revestimentos"].extend(e.get("revestimentos", []))  # Collect revestimentos
                    excel_data["confidence"] = max(excel_data["confidence"], e.get("confidence", 0))
    
    # Use merged analyses
    dxf_analysis = project.get("merged_dxf_analysis") or (
        project["dxf_analyses"][0] if project["dxf_analyses"] else {"success": False}
    )
    pdf_analysis = project.get("merged_pdf_analysis") or (
        project["pdf_analyses"][0] if project["pdf_analyses"] else {"success": False}
    )
    
    has_dxf = dxf_analysis.get("success", False)
    has_pdf = pdf_analysis.get("success", False)
    
    if not has_dxf and not has_pdf and not has_excel:
        raise HTTPException(
            status_code=400, 
            detail="Nenhum dado de análise disponível. Por favor carregue ficheiros primeiro."
        )
    
    # Create pricing parameters
    params = PricingParameters()
    if request.parameters:
        for key, value in request.parameters.model_dump(exclude_none=True).items():
            if hasattr(params, key):
                setattr(params, key, value)
    
    # Calculate budget
    calculator = BudgetCalculator(params)
    
    # Generate project reference
    project_reference = f"ORC-{request.project_id.upper()}"
    
    budget = calculator.calculate_budget(
        dxf_data=dxf_analysis,
        pdf_data=pdf_analysis,
        surface_treatment=request.surface_treatment,
        project_name=project["name"],
        project_reference=project_reference,
        material_code=request.material_code,
        unit_multiplier=request.unit_multiplier,
        auto_detect_multiplier=request.auto_detect_multiplier,
        excel_data=excel_data  # Pass Excel data for accurate weights
    )
    
    # Add AI recommendations if method exists
    if hasattr(calculator, 'get_ai_recommendations'):
        budget["recommendations"] = calculator.get_ai_recommendations()
    else:
        budget["recommendations"] = []
    
    # Determine primary data source
    if has_excel:
        quantity_source = "Excel FLYSTEEL (95%+ precisão)"
        confidence = excel_data.get("confidence", 0.95)
    elif has_dxf:
        quantity_source = "DXF (estimativa geométrica)"
        confidence = 0.70
    else:
        quantity_source = "PDF (extração de texto)"
        confidence = 0.60
    
    # Add source information
    budget["data_sources"] = {
        "excel_files_used": len(excel_analyses),
        "dxf_files_used": len(project["dxf_analyses"]),
        "pdf_files_used": len(project["pdf_analyses"]),
        "quantity_source": quantity_source,
        "specifications_source": "PDF" if has_pdf else ("Excel" if has_excel else "DXF"),
        "confidence": round(confidence, 4)
    }
    
    # If Excel data available, override structure weight
    if excel_data:
        budget["excel_quantities"] = {
            "estrutura_metalica_kg": excel_data["estrutura_metalica_kg"],
            "madres_galvanizadas_kg": excel_data["madres_galvanizadas_kg"],
            "pintura_intumescente_kg": excel_data["estrutura_metalica_kg"],  # Only non-galv steel
            "total_geral_kg": excel_data["total_geral_kg"],
            "confidence": excel_data["confidence"]
        }
    
    # ============== DRAWING EXTRACTION & DISCREPANCY ANALYSIS ==============
    # Check if drawing extraction was performed and compare with Excel
    drawing_extraction = project.get("drawing_extraction")
    discrepancy_alerts = []
    items_from_drawings = []
    
    if drawing_extraction and HAS_DRAWING_EXTRACTOR:
        # Get alerts from drawing extraction
        raw_alerts = drawing_extraction.get("discrepancy_alerts", [])
        
        # If we have Excel data, run comparison
        if excel_data and project.get("pdf_drawings"):
            try:
                # Re-run extraction with Excel comparison
                drawing_paths = [d["path"] for d in project["pdf_drawings"]]
                updated_extraction = extract_quantities_from_drawings(
                    pdf_paths=drawing_paths,
                    dxf_data=project.get("dxf_analyses", []),
                    excel_data=excel_data
                )
                raw_alerts = updated_extraction.get("discrepancy_alerts", [])
                project["drawing_extraction"] = updated_extraction
            except Exception as e:
                print(f"[DrawingExtractor] Erro na comparação: {str(e)}")
        
        # Process alerts
        for alert in raw_alerts:
            discrepancy_alerts.append({
                "type": alert.get("alert_type"),
                "item": alert.get("designation"),
                "item_type": alert.get("item_type"),
                "excel_value": alert.get("excel_value"),
                "drawing_value": alert.get("drawing_value"),
                "unit": alert.get("unit"),
                "priority": alert.get("priority"),
                "message": alert.get("message"),
                "source": alert.get("source_file")
            })
            
            # If item is missing in Excel, add to budget items
            if alert.get("alert_type") == "missing_in_excel":
                items_from_drawings.append({
                    "item_type": alert.get("item_type"),
                    "designation": alert.get("designation"),
                    "quantity": alert.get("drawing_value"),
                    "unit": alert.get("unit"),
                    "source": "PDF/DXF Drawings",
                    "note": "Item encontrado nos desenhos mas não nos ficheiros Excel"
                })
        
        # Add drawing totals to budget
        budget["drawing_quantities"] = {
            "caleiros_ml": drawing_extraction.get("totals", {}).get("caleiros_ml", 0),
            "palas_m2": drawing_extraction.get("totals", {}).get("palas_m2", 0),
            "paineis_cobertura_m2": drawing_extraction.get("totals", {}).get("paineis_cobertura_m2", 0),
            "paineis_fachada_m2": drawing_extraction.get("totals", {}).get("paineis_fachada_m2", 0),
            "files_analyzed": drawing_extraction.get("files_processed", 0)
        }
    
    # Add discrepancy information to budget
    budget["discrepancy_alerts"] = discrepancy_alerts
    budget["items_from_drawings"] = items_from_drawings
    
    # Add summary of data sources with drawing info
    budget["data_sources"]["pdf_drawings_analyzed"] = len(project.get("pdf_drawings", []))
    budget["data_sources"]["discrepancies_found"] = len(discrepancy_alerts)
    budget["data_sources"]["items_added_from_drawings"] = len(items_from_drawings)
    
    # Store budget in project
    project["budget"] = budget
    project["status"] = "calculated"
    
    return budget


@app.post("/api/quick-estimate")
async def quick_estimate(request: QuickEstimateRequest):
    """Get a quick estimate based on weight and complexity"""
    estimate = calculate_quick_estimate(
        weight_kg=request.weight_kg,
        complexity=request.complexity
    )
    return estimate


@app.post("/api/projects/{project_id}/simulate-margin")
async def simulate_margin(project_id: str, target_margin_pct: float = 25.0):
    """Simulate different profit margins"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    budget = project.get("budget")
    
    if not budget:
        raise HTTPException(status_code=400, detail="Nenhum orçamento calculado ainda")
    
    summary = budget.get("summary", {})
    subtotal = summary.get("totals", {}).get("subtotal", 0)
    
    new_margin = subtotal * (target_margin_pct / 100)
    new_total = subtotal + new_margin
    
    return {
        "original_margin_pct": summary.get("metrics", {}).get("profit_margin_pct", 20),
        "target_margin_pct": target_margin_pct,
        "original_total": summary.get("totals", {}).get("total_quote", 0),
        "new_margin": round(new_margin, 2),
        "new_total": round(new_total, 2)
    }


# ============== Export Endpoints ==============

@app.get("/api/projects/{project_id}/export/json")
async def export_json(project_id: str):
    """Export budget as JSON"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    budget = project.get("budget")
    
    if not budget:
        raise HTTPException(status_code=400, detail="Nenhum orçamento para exportar")
    
    export_path = EXPORT_DIR / f"quote_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(budget, f, indent=2, ensure_ascii=False)
    
    return FileResponse(
        path=export_path,
        filename=export_path.name,
        media_type="application/json"
    )


@app.get("/api/projects/{project_id}/export/pdf")
async def export_pdf(project_id: str):
    """Export budget as professional PDF document"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    budget = project.get("budget")
    
    if not budget:
        raise HTTPException(status_code=400, detail="Nenhum orçamento para exportar")
    
    # Create PDF
    export_path = EXPORT_DIR / f"orcamento_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    doc = SimpleDocTemplate(
        str(export_path),
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#0ea5e9'),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#6b7280'),
        alignment=TA_CENTER,
        spaceAfter=20
    )
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1f2937'),
        spaceBefore=15,
        spaceAfter=10
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9
    )
    
    elements = []
    
    # Header
    elements.append(Paragraph("AluQuote AI", title_style))
    elements.append(Paragraph("Orçamento de Serralharia de Alumínio", subtitle_style))
    
    # Project Info
    summary = budget.get("summary", {})
    project_info = [
        ["Projeto:", summary.get("project_name", "N/A")],
        ["Data:", datetime.now().strftime("%d/%m/%Y %H:%M")],
        ["Referência:", f"ORÇ-{project_id.upper()}"]
    ]
    
    info_table = Table(project_info, colWidths=[80, 300])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#6b7280')),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#1f2937')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 15))
    
    # Summary Stats
    elements.append(Paragraph("Resumo do Orçamento", section_style))
    
    quantities = summary.get("quantities", {})
    totals = summary.get("totals", {})
    metrics = summary.get("metrics", {})
    
    summary_data = [
        ["Descrição", "Valor"],
        ["Total de Perfis", str(quantities.get("total_profiles", 0))],
        ["Quantidade Total", str(quantities.get("total_quantity", 0))],
        ["Peso Total (kg)", f"{quantities.get('total_weight_kg', 0):.2f}"],
        ["Horas de Produção", f"{metrics.get('production_hours', 0):.1f}h"],
        ["Fator de Desperdício", f"{metrics.get('waste_percentage', 0):.1f}%"],
    ]
    
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0ea5e9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 15))
    
    # Line Items
    elements.append(Paragraph("Itens do Orçamento", section_style))
    
    line_items = budget.get("line_items", [])
    
    items_header = ["#", "Referência", "Descrição", "Qtd", "Peso(kg)", "Material", "Tratam.", "M.O.", "Total"]
    items_data = [items_header]
    
    for item in line_items:
        costs = item.get("costs", {})
        geometry = item.get("geometry", {})
        row = [
            str(item.get("line_id", "")),
            item.get("reference", "-")[:15],
            item.get("description", "-")[:20],
            str(item.get("quantity", 0)),
            f"{geometry.get('weight_kg', 0):.2f}",
            f"{costs.get('raw_material', 0):.2f}",
            f"{costs.get('surface_treatment', 0):.2f}",
            f"{costs.get('labor', 0):.2f}",
            f"{item.get('total_cost', 0):.2f}"
        ]
        items_data.append(row)
    
    items_table = Table(items_data, colWidths=[20, 55, 80, 25, 40, 45, 40, 35, 45])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 15))
    
    # Cost Breakdown
    elements.append(Paragraph("Decomposição de Custos", section_style))
    
    cost_breakdown = summary.get("cost_breakdown", {})
    breakdown_data = [["Categoria", "Valor (EUR)"]]
    
    cost_labels = {
        "raw_material": "Matéria-Prima",
        "transformation": "Transformação",
        "surface_treatment": "Tratamento Superfície",
        "labor": "Mão de Obra",
        "accessories": "Acessórios",
        "waste_allowance": "Provisão Desperdício",
        "overhead": "Custos Gerais"
    }
    
    for key, value in cost_breakdown.items():
        label = cost_labels.get(key, key.replace("_", " ").title())
        breakdown_data.append([label, f"{value:.2f} €"])
    
    breakdown_table = Table(breakdown_data, colWidths=[250, 150])
    breakdown_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#059669')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fdf4')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(breakdown_table)
    elements.append(Spacer(1, 20))
    
    # Totals
    totals_data = [
        ["Subtotal:", f"{totals.get('subtotal', 0):.2f} €"],
        ["Margem de Lucro:", f"{totals.get('profit_margin', 0):.2f} €"],
        ["TOTAL ORÇAMENTO:", f"{totals.get('total_quote', 0):.2f} €"],
    ]
    
    totals_table = Table(totals_data, colWidths=[300, 100])
    totals_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#0ea5e9')),
        ('FONTSIZE', (0, -1), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#0ea5e9')),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 30))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#9ca3af'),
        alignment=TA_CENTER
    )
    elements.append(Paragraph("Orçamento gerado automaticamente por AluQuote AI | Válido por 30 dias", footer_style))
    elements.append(Paragraph(f"Documento: ORÇ-{project_id.upper()} | {datetime.now().strftime('%d/%m/%Y')}", footer_style))
    
    # Build PDF
    doc.build(elements)
    
    return FileResponse(
        path=export_path,
        filename=f"orcamento_{project_id}.pdf",
        media_type="application/pdf"
    )


@app.get("/api/projects/{project_id}/export/csv")
async def export_csv(project_id: str):
    """Export budget line items as CSV"""
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    budget = project.get("budget")
    
    if not budget:
        raise HTTPException(status_code=400, detail="Nenhum orçamento para exportar")
    
    import csv
    
    export_path = EXPORT_DIR / f"quote_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    line_items = budget.get("line_items", [])
    
    with open(export_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            "Linha", "Referência", "Descrição", "Qtd", "Fonte Qtd",
            "Perímetro (mm)", "Comprimento (mm)", "Peso (kg)",
            "Custo Material", "Custo Tratamento", "Custo M.O.",
            "Custo Unitário", "Custo Total", "Confiança"
        ])
        
        # Data rows
        for item in line_items:
            geometry = item.get("geometry", {})
            costs = item.get("costs", {})
            writer.writerow([
                item["line_id"],
                item["reference"],
                item["description"],
                item["quantity"],
                item.get("quantity_source", ""),
                geometry.get("perimeter_mm", 0),
                geometry.get("length_mm", 0),
                geometry.get("weight_kg", 0),
                costs.get("raw_material", 0),
                costs.get("surface_treatment", 0),
                costs.get("labor", 0),
                item["unit_cost"],
                item["total_cost"],
                item.get("correlation_confidence", 0)
            ])
    
    return FileResponse(
        path=export_path,
        filename=export_path.name,
        media_type="text/csv"
    )


# ============== Pricing Parameters ==============

@app.get("/api/pricing-parameters")
async def get_default_parameters():
    """Get default pricing parameters"""
    return PricingParameters().to_dict()


@app.get("/api/surface-treatments")
async def get_surface_treatments():
    """Get available surface treatment options"""
    params = PricingParameters()
    return {
        "options": [
            {"id": "none", "name": "Sem Tratamento", "price_eur_m2": 0},
            {"id": "galvanizado", "name": "Galvanizado", "price_eur_m2": 0.45},
            {"id": "anodizing_natural", "name": "Anodizacao Natural", "price_eur_m2": params.anodizing_natural_eur_m2},
            {"id": "anodizing_colored", "name": "Anodizacao Colorida", "price_eur_m2": params.anodizing_colored_eur_m2},
            {"id": "powder_coating_standard", "name": "Lacagem Standard", "price_eur_m2": params.powder_coating_standard_eur_m2},
            {"id": "powder_coating_qualicoat", "name": "Lacagem Qualicoat", "price_eur_m2": params.powder_coating_qualicoat_eur_m2},
            {"id": "powder_coating_seaside", "name": "Lacagem Seaside (Maritimo)", "price_eur_m2": params.powder_coating_seaside_eur_m2},
        ]
    }


@app.get("/api/materials")
async def get_materials():
    """Get available materials with properties"""
    materials = get_available_materials()
    
    # Group by category
    steel = [m for m in materials if m['code'].startswith('S') or m['code'] == 'GALV']
    aluminum = [m for m in materials if m['code'].startswith('AL')]
    stainless = [m for m in materials if m['code'].startswith('INOX')]
    
    return {
        "success": True,
        "materials": materials,
        "grouped": {
            "steel": steel,
            "aluminum": aluminum,
            "stainless_steel": stainless
        }
    }


# ============== Main Entry ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
