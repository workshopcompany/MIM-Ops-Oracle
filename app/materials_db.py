"""
materials_db.py — MIM-Ops thermal / mechanical material property database
for temperature, cooling, and shrinkage analysis (Day 4+).

Covers all 35 materials defined in material_property.txt:
  - CATAMOLD feedstocks  (9 materials)
  - WAXBASE  feedstocks  (9 materials)
  - Engineering plastics (17 materials)

Design principle:
  - Tmelt_C / Tmold_C / T_eject_C come from the feedstock/binder system
    (match material_property.txt Tmelt/Tmold values exactly).
  - Cp, k, rho, CTE, compressibility, sintering_shrinkage are
    base-metal or polymer properties — shared between CATAMOLD and
    WAXBASE variants of the same alloy (binder burns out; final part
    properties are identical).
  - Plastics use polymer thermal properties; sintering_shrinkage = 0
    (no sintering step).

Sources: ASM Handbook, BASF CATAMOLD datasheets, MIM industry standards,
         Granta CES EduPack polymer database.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helper: shared metal base properties (binder-independent)
# ─────────────────────────────────────────────────────────────────────────────
_METAL_BASE = {
    "304L": {
        "Cp_J_kgK": 500.0, "k_W_mK": 16.0, "rho_kg_m3": 7900.0,
        "CTE_per_C": 17.0e-6, "compressibility_per_MPa": 4.5e-5,
        "sintering_shrinkage": 0.150,
    },
    "4140": {
        "Cp_J_kgK": 473.0, "k_W_mK": 42.6, "rho_kg_m3": 7700.0,
        "CTE_per_C": 12.3e-6, "compressibility_per_MPa": 4.2e-5,
        "sintering_shrinkage": 0.135,
    },
    "17-4PH": {
        "Cp_J_kgK": 460.0, "k_W_mK": 18.0, "rho_kg_m3": 7780.0,
        "CTE_per_C": 11.0e-6, "compressibility_per_MPa": 4.0e-5,
        "sintering_shrinkage": 0.145,
    },
    "316L": {
        "Cp_J_kgK": 500.0, "k_W_mK": 15.0, "rho_kg_m3": 7950.0,
        "CTE_per_C": 16.0e-6, "compressibility_per_MPa": 4.5e-5,
        "sintering_shrinkage": 0.150,
    },
    "Fe-Ni": {
        "Cp_J_kgK": 480.0, "k_W_mK": 20.0, "rho_kg_m3": 7650.0,
        "CTE_per_C": 13.0e-6, "compressibility_per_MPa": 4.2e-5,
        "sintering_shrinkage": 0.140,
    },
    "Al6061": {
        "Cp_J_kgK": 896.0, "k_W_mK": 167.0, "rho_kg_m3": 2700.0,
        "CTE_per_C": 23.6e-6, "compressibility_per_MPa": 1.3e-5,
        "sintering_shrinkage": 0.180,
    },
    "Al7075": {
        "Cp_J_kgK": 960.0, "k_W_mK": 130.0, "rho_kg_m3": 2810.0,
        "CTE_per_C": 23.4e-6, "compressibility_per_MPa": 1.4e-5,
        "sintering_shrinkage": 0.175,
    },
    "Ti-6Al-4V": {
        "Cp_J_kgK": 520.0, "k_W_mK": 7.0, "rho_kg_m3": 4430.0,
        "CTE_per_C": 8.6e-6, "compressibility_per_MPa": 3.0e-5,
        "sintering_shrinkage": 0.160,
    },
    "TiH2": {
        "Cp_J_kgK": 540.0, "k_W_mK": 6.5, "rho_kg_m3": 4500.0,
        "CTE_per_C": 8.9e-6, "compressibility_per_MPa": 3.1e-5,
        "sintering_shrinkage": 0.165,
    },
}

MATERIALS_DB = {

    # ═══════════════════════════════════════════════════════════════════
    # CATAMOLD feedstocks (polyacetal/POM-based binder, catalytic debind)
    # ═══════════════════════════════════════════════════════════════════
    "CATAMOLD-304L":      {"Tmelt_C": 185.0, "Tmold_C": 40.0, "T_eject_C": 115.0, **_METAL_BASE["304L"]},
    "CATAMOLD-4140":      {"Tmelt_C": 190.0, "Tmold_C": 45.0, "T_eject_C": 120.0, **_METAL_BASE["4140"]},
    "CATAMOLD-17-4PH":    {"Tmelt_C": 185.0, "Tmold_C": 40.0, "T_eject_C": 115.0, **_METAL_BASE["17-4PH"]},
    "CATAMOLD-316L":      {"Tmelt_C": 185.0, "Tmold_C": 40.0, "T_eject_C": 115.0, **_METAL_BASE["316L"]},
    "CATAMOLD-Fe-Ni":     {"Tmelt_C": 182.0, "Tmold_C": 40.0, "T_eject_C": 112.0, **_METAL_BASE["Fe-Ni"]},
    "CATAMOLD-Al6061":    {"Tmelt_C": 170.0, "Tmold_C": 35.0, "T_eject_C": 105.0, **_METAL_BASE["Al6061"]},
    "CATAMOLD-Al7075":    {"Tmelt_C": 175.0, "Tmold_C": 35.0, "T_eject_C": 108.0, **_METAL_BASE["Al7075"]},
    "CATAMOLD-Ti-6Al-4V": {"Tmelt_C": 195.0, "Tmold_C": 50.0, "T_eject_C": 125.0, **_METAL_BASE["Ti-6Al-4V"]},
    "CATAMOLD-TiH2":      {"Tmelt_C": 180.0, "Tmold_C": 45.0, "T_eject_C": 115.0, **_METAL_BASE["TiH2"]},

    # ═══════════════════════════════════════════════════════════════════
    # WAXBASE feedstocks (paraffin wax + polymer binder, solvent/thermal debind)
    # Same metal base properties as CATAMOLD — only Tmelt/Tmold differ
    # ═══════════════════════════════════════════════════════════════════
    "WAXBASE-304L":      {"Tmelt_C": 170.0, "Tmold_C": 35.0, "T_eject_C": 100.0, **_METAL_BASE["304L"]},
    "WAXBASE-4140":      {"Tmelt_C": 175.0, "Tmold_C": 40.0, "T_eject_C": 105.0, **_METAL_BASE["4140"]},
    "WAXBASE-17-4PH":    {"Tmelt_C": 170.0, "Tmold_C": 35.0, "T_eject_C": 100.0, **_METAL_BASE["17-4PH"]},
    "WAXBASE-316L":      {"Tmelt_C": 170.0, "Tmold_C": 35.0, "T_eject_C": 100.0, **_METAL_BASE["316L"]},
    "WAXBASE-Fe-Ni":     {"Tmelt_C": 168.0, "Tmold_C": 35.0, "T_eject_C":  98.0, **_METAL_BASE["Fe-Ni"]},
    "WAXBASE-Al6061":    {"Tmelt_C": 160.0, "Tmold_C": 30.0, "T_eject_C":  95.0, **_METAL_BASE["Al6061"]},
    "WAXBASE-Al7075":    {"Tmelt_C": 165.0, "Tmold_C": 30.0, "T_eject_C":  98.0, **_METAL_BASE["Al7075"]},
    "WAXBASE-Ti-6Al-4V": {"Tmelt_C": 180.0, "Tmold_C": 40.0, "T_eject_C": 110.0, **_METAL_BASE["Ti-6Al-4V"]},
    "WAXBASE-TiH2":      {"Tmelt_C": 172.0, "Tmold_C": 38.0, "T_eject_C": 105.0, **_METAL_BASE["TiH2"]},

    # ═══════════════════════════════════════════════════════════════════
    # Engineering Plastics
    # T_eject_C ~ Tmold + 60~80°C (HDT-based safe ejection temp)
    # sintering_shrinkage = 0 (no sintering in plastic IM)
    # CTE / Cp / k from Granta CES / ISO 11359
    # ═══════════════════════════════════════════════════════════════════
    "PP": {
        "Tmelt_C": 230.0, "Tmold_C":  40.0, "T_eject_C":  95.0,
        "Cp_J_kgK": 1900.0, "k_W_mK": 0.22, "rho_kg_m3":  910.0,
        "CTE_per_C": 150.0e-6, "compressibility_per_MPa": 2.0e-4, "sintering_shrinkage": 0.0,
    },
    "PE-HD": {
        "Tmelt_C": 220.0, "Tmold_C":  40.0, "T_eject_C":  90.0,
        "Cp_J_kgK": 2100.0, "k_W_mK": 0.44, "rho_kg_m3":  950.0,
        "CTE_per_C": 170.0e-6, "compressibility_per_MPa": 2.2e-4, "sintering_shrinkage": 0.0,
    },
    "PE-LD": {
        "Tmelt_C": 210.0, "Tmold_C":  35.0, "T_eject_C":  85.0,
        "Cp_J_kgK": 2200.0, "k_W_mK": 0.33, "rho_kg_m3":  920.0,
        "CTE_per_C": 200.0e-6, "compressibility_per_MPa": 2.4e-4, "sintering_shrinkage": 0.0,
    },
    "ABS": {
        "Tmelt_C": 240.0, "Tmold_C":  60.0, "T_eject_C": 120.0,
        "Cp_J_kgK": 1400.0, "k_W_mK": 0.17, "rho_kg_m3": 1050.0,
        "CTE_per_C":  90.0e-6, "compressibility_per_MPa": 1.5e-4, "sintering_shrinkage": 0.0,
    },
    "PC": {
        "Tmelt_C": 300.0, "Tmold_C":  80.0, "T_eject_C": 145.0,
        "Cp_J_kgK": 1260.0, "k_W_mK": 0.20, "rho_kg_m3": 1200.0,
        "CTE_per_C":  65.0e-6, "compressibility_per_MPa": 1.3e-4, "sintering_shrinkage": 0.0,
    },
    "PC+ABS": {
        "Tmelt_C": 260.0, "Tmold_C":  70.0, "T_eject_C": 130.0,
        "Cp_J_kgK": 1340.0, "k_W_mK": 0.19, "rho_kg_m3": 1130.0,
        "CTE_per_C":  75.0e-6, "compressibility_per_MPa": 1.4e-4, "sintering_shrinkage": 0.0,
    },
    "PA6": {
        "Tmelt_C": 245.0, "Tmold_C":  70.0, "T_eject_C": 130.0,
        "Cp_J_kgK": 1680.0, "k_W_mK": 0.25, "rho_kg_m3": 1130.0,
        "CTE_per_C":  80.0e-6, "compressibility_per_MPa": 1.6e-4, "sintering_shrinkage": 0.0,
    },
    "PA66": {
        "Tmelt_C": 265.0, "Tmold_C":  80.0, "T_eject_C": 145.0,
        "Cp_J_kgK": 1700.0, "k_W_mK": 0.26, "rho_kg_m3": 1140.0,
        "CTE_per_C":  80.0e-6, "compressibility_per_MPa": 1.6e-4, "sintering_shrinkage": 0.0,
    },
    "PA66+GF30": {
        "Tmelt_C": 285.0, "Tmold_C":  85.0, "T_eject_C": 150.0,
        "Cp_J_kgK": 1500.0, "k_W_mK": 0.36, "rho_kg_m3": 1300.0,
        "CTE_per_C":  35.0e-6, "compressibility_per_MPa": 1.1e-4, "sintering_shrinkage": 0.0,
    },
    "PA12": {
        "Tmelt_C": 180.0, "Tmold_C":  40.0, "T_eject_C": 105.0,
        "Cp_J_kgK": 1680.0, "k_W_mK": 0.23, "rho_kg_m3": 1010.0,
        "CTE_per_C": 100.0e-6, "compressibility_per_MPa": 1.7e-4, "sintering_shrinkage": 0.0,
    },
    "POM": {
        "Tmelt_C": 200.0, "Tmold_C":  90.0, "T_eject_C": 155.0,
        "Cp_J_kgK": 1470.0, "k_W_mK": 0.31, "rho_kg_m3": 1410.0,
        "CTE_per_C": 110.0e-6, "compressibility_per_MPa": 1.5e-4, "sintering_shrinkage": 0.0,
    },
    "PBT": {
        "Tmelt_C": 240.0, "Tmold_C":  80.0, "T_eject_C": 145.0,
        "Cp_J_kgK": 1250.0, "k_W_mK": 0.29, "rho_kg_m3": 1300.0,
        "CTE_per_C":  70.0e-6, "compressibility_per_MPa": 1.4e-4, "sintering_shrinkage": 0.0,
    },
    "PET": {
        "Tmelt_C": 250.0, "Tmold_C":  80.0, "T_eject_C": 145.0,
        "Cp_J_kgK": 1300.0, "k_W_mK": 0.29, "rho_kg_m3": 1380.0,
        "CTE_per_C":  65.0e-6, "compressibility_per_MPa": 1.3e-4, "sintering_shrinkage": 0.0,
    },
    "PPS": {
        "Tmelt_C": 310.0, "Tmold_C": 130.0, "T_eject_C": 195.0,
        "Cp_J_kgK": 1090.0, "k_W_mK": 0.29, "rho_kg_m3": 1350.0,
        "CTE_per_C":  55.0e-6, "compressibility_per_MPa": 1.2e-4, "sintering_shrinkage": 0.0,
    },
    "PPS+GF40": {
        "Tmelt_C": 320.0, "Tmold_C": 135.0, "T_eject_C": 200.0,
        "Cp_J_kgK": 1000.0, "k_W_mK": 0.40, "rho_kg_m3": 1650.0,
        "CTE_per_C":  25.0e-6, "compressibility_per_MPa": 0.9e-4, "sintering_shrinkage": 0.0,
    },
    "PEEK": {
        "Tmelt_C": 370.0, "Tmold_C": 160.0, "T_eject_C": 220.0,
        "Cp_J_kgK": 1340.0, "k_W_mK": 0.25, "rho_kg_m3": 1320.0,
        "CTE_per_C":  47.0e-6, "compressibility_per_MPa": 1.1e-4, "sintering_shrinkage": 0.0,
    },
    "PEI": {
        "Tmelt_C": 340.0, "Tmold_C": 150.0, "T_eject_C": 210.0,
        "Cp_J_kgK": 1260.0, "k_W_mK": 0.22, "rho_kg_m3": 1270.0,
        "CTE_per_C":  56.0e-6, "compressibility_per_MPa": 1.2e-4, "sintering_shrinkage": 0.0,
    },
    "PSU": {
        "Tmelt_C": 320.0, "Tmold_C": 145.0, "T_eject_C": 205.0,
        "Cp_J_kgK": 1300.0, "k_W_mK": 0.26, "rho_kg_m3": 1240.0,
        "CTE_per_C":  55.0e-6, "compressibility_per_MPa": 1.2e-4, "sintering_shrinkage": 0.0,
    },
    "LCP": {
        "Tmelt_C": 330.0, "Tmold_C": 140.0, "T_eject_C": 200.0,
        "Cp_J_kgK": 1150.0, "k_W_mK": 0.30, "rho_kg_m3": 1420.0,
        "CTE_per_C":  10.0e-6, "compressibility_per_MPa": 0.8e-4, "sintering_shrinkage": 0.0,
    },
    "PMMA": {
        "Tmelt_C": 230.0, "Tmold_C":  70.0, "T_eject_C": 130.0,
        "Cp_J_kgK": 1460.0, "k_W_mK": 0.19, "rho_kg_m3": 1180.0,
        "CTE_per_C":  70.0e-6, "compressibility_per_MPa": 1.5e-4, "sintering_shrinkage": 0.0,
    },
    "HIPS": {
        "Tmelt_C": 220.0, "Tmold_C":  60.0, "T_eject_C": 115.0,
        "Cp_J_kgK": 1300.0, "k_W_mK": 0.17, "rho_kg_m3": 1040.0,
        "CTE_per_C":  80.0e-6, "compressibility_per_MPa": 1.5e-4, "sintering_shrinkage": 0.0,
    },
    "PVC": {
        "Tmelt_C": 190.0, "Tmold_C":  55.0, "T_eject_C": 110.0,
        "Cp_J_kgK": 1050.0, "k_W_mK": 0.16, "rho_kg_m3": 1380.0,
        "CTE_per_C":  80.0e-6, "compressibility_per_MPa": 1.6e-4, "sintering_shrinkage": 0.0,
    },
    "TPU": {
        "Tmelt_C": 200.0, "Tmold_C":  50.0, "T_eject_C": 105.0,
        "Cp_J_kgK": 1750.0, "k_W_mK": 0.20, "rho_kg_m3": 1200.0,
        "CTE_per_C": 150.0e-6, "compressibility_per_MPa": 2.0e-4, "sintering_shrinkage": 0.0,
    },
    "TPE": {
        "Tmelt_C": 190.0, "Tmold_C":  45.0, "T_eject_C": 100.0,
        "Cp_J_kgK": 1800.0, "k_W_mK": 0.19, "rho_kg_m3": 1180.0,
        "CTE_per_C": 160.0e-6, "compressibility_per_MPa": 2.1e-4, "sintering_shrinkage": 0.0,
    },
    "EPDM": {
        "Tmelt_C": 180.0, "Tmold_C":  40.0, "T_eject_C":  95.0,
        "Cp_J_kgK": 2000.0, "k_W_mK": 0.25, "rho_kg_m3": 1150.0,
        "CTE_per_C": 175.0e-6, "compressibility_per_MPa": 2.3e-4, "sintering_shrinkage": 0.0,
    },
}

# Default fallback
DEFAULT_MATERIAL = {
    "Tmelt_C": 200.0, "Tmold_C": 50.0, "T_eject_C": 120.0,
    "Cp_J_kgK": 480.0, "k_W_mK": 18.0, "rho_kg_m3": 7800.0,
    "CTE_per_C": 12.0e-6, "compressibility_per_MPa": 4.0e-5,
    "sintering_shrinkage": 0.145,
}


def get_material(name: str) -> dict:
    """Return properties by name (case-insensitive). Falls back to DEFAULT_MATERIAL."""
    for k, v in MATERIALS_DB.items():
        if k.lower() == name.strip().lower():
            return v
    return DEFAULT_MATERIAL


def list_materials() -> list:
    """Return all material names in the database."""
    return list(MATERIALS_DB.keys())


def get_material_group(name: str) -> str:
    """Classify material: 'catamold' | 'waxbase' | 'plastic'"""
    n = name.strip().upper()
    if n.startswith("CATAMOLD"):
        return "catamold"
    if n.startswith("WAXBASE"):
        return "waxbase"
    return "plastic"
