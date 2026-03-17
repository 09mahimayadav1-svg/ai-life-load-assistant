from typing import Dict, List
import pandas as pd

def _standardize_name(value: str) -> str:
    return str(value).strip().lower()

def _inventory_lookup(inventory_df: pd.DataFrame) -> Dict[str, Dict]:
    lookup = {}
    for _, row in inventory_df.iterrows():
        lookup[_standardize_name(row["Item_Name"])] = {
            "qty": float(row["Quantity_Available"]) if pd.notna(row["Quantity_Available"]) else 0.0,
            "unit": row["Unit"],
            "status": row["Status"],
        }
    return lookup

def _scale_factor(members: int) -> float:
    mapping = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 2.5}
    return mapping.get(members, members / 2)

def _recipe_ingredients(recipe_id: str, recipe_ing_df: pd.DataFrame, members: int) -> pd.DataFrame:
    items = recipe_ing_df[recipe_ing_df["Recipe_ID"] == recipe_id].copy()
    items["Required_Qty"] = items["Qty_For_2"].astype(float) * _scale_factor(members)
    return items

def _match_recipe(recipe_row, recipe_ing_df, inventory_df, members):
    inv = _inventory_lookup(inventory_df)
    items = _recipe_ingredients(recipe_row["Recipe_ID"], recipe_ing_df, members)

    missing_mandatory, missing_optional = [], []
    ingredient_rows = []

    for _, ing in items.iterrows():
        ingredient_name = ing["Ingredient_Name"]
        key = _standardize_name(ingredient_name)
        required = float(ing["Required_Qty"])
        mandatory = str(ing["Mandatory"]).strip().lower() == "yes"
        available_qty = 0.0
        inventory_unit = ing["Unit"]

        if key in inv:
            available_qty = inv[key]["qty"]
            inventory_unit = inv[key]["unit"]

        ingredient_rows.append({
            "ingredient": ingredient_name,
            "required_qty": required,
            "unit": ing["Unit"],
            "available_qty": available_qty,
            "inventory_unit": inventory_unit,
            "mandatory": "Yes" if mandatory else "No",
        })

        if key not in inv:
            msg = f"{ingredient_name} missing from inventory master"
            (missing_mandatory if mandatory else missing_optional).append(msg)
            continue

        if available_qty < required:
            msg = f"{ingredient_name}: need {required:g} {ing['Unit']}, available {available_qty:g} {inventory_unit}"
            (missing_mandatory if mandatory else missing_optional).append(msg)

    status = "Not Available" if missing_mandatory else "Partially Available" if missing_optional else "Available"
    return {
        "recipe_id": recipe_row["Recipe_ID"],
        "recipe_name": recipe_row["Recipe_Name"],
        "status": status,
        "meal_type": recipe_row["Meal_Type"],
        "total_time_min": int(recipe_row.get("Total_Time_Min", 25)),
        "difficulty": recipe_row.get("Difficulty", "Easy"),
        "missing_mandatory": missing_mandatory,
        "missing_optional": missing_optional,
        "ingredient_list": ingredient_rows,
    }

def _recommend_limit(workload_level: str, stress_score: int) -> int:
    if workload_level == "Heavy workload" or stress_score >= 8:
        return 20
    if workload_level == "Moderate workload" or stress_score >= 6:
        return 30
    return 45

def _reason_line(item, workload_level: str, stress_score: int, context_label: str = "day") -> str:
    if context_label == "evening":
        if workload_level == "Heavy workload" or stress_score >= 8:
            return "kept quick because your evening looks packed"
        if workload_level == "Moderate workload" or stress_score >= 6:
            return "fits a moderately busy evening"
        return "works well for a relaxed evening with time for a fuller meal"

    if item["total_time_min"] <= 20:
        return "best for a very busy slot"
    if workload_level == "Moderate workload" or stress_score >= 6:
        return "good for a moderately busy day"
    return "suits a lighter day"

def _diversify_recommendations(available, time_limit, meal_type):
    filtered = [x for x in available if x["total_time_min"] <= time_limit]
    base_pool = filtered if filtered else available

    if meal_type != "Any":
        return base_pool[:4]

    picks = []
    breakfast = next((x for x in base_pool if "breakfast" in str(x["meal_type"]).lower()), None)
    lunch = next((x for x in base_pool if "lunch" in str(x["meal_type"]).lower()), None)
    dinner = next((x for x in base_pool if "dinner" in str(x["meal_type"]).lower()), None)

    for item in [breakfast, lunch, dinner]:
        if item and item not in picks:
            picks.append(item)

    for item in base_pool:
        if item not in picks:
            picks.append(item)
        if len(picks) >= 4:
            break

    return picks[:4]

def _dinner_recommendations(available, workload_level: str, stress_score: int):
    dinner_pool = [x for x in available if "dinner" in str(x["meal_type"]).lower() or "lunch/dinner" in str(x["meal_type"]).lower()]
    if not dinner_pool:
        dinner_pool = available[:]

    if workload_level == "Heavy workload" or stress_score >= 8:
        ranked = sorted(dinner_pool, key=lambda x: (x["total_time_min"] > 20, x["total_time_min"]))
    elif workload_level == "Moderate workload" or stress_score >= 6:
        ranked = sorted(
            dinner_pool,
            key=lambda x: (0 if 20 <= x["total_time_min"] <= 40 else 1, abs(x["total_time_min"] - 30))
        )
    else:
        ranked = sorted(
            dinner_pool,
            key=lambda x: (0 if 25 <= x["total_time_min"] <= 50 else 1, -x["total_time_min"])
        )

    return ranked[:4]

def get_inventory_driven_meal_plan(
    excel_path: str,
    meal_type: str="Any",
    members: int=2,
    preferences: Dict|None=None,
    workload_level: str="Moderate workload",
    stress_score: int=5,
    context_label: str="day",
) -> Dict:
    inventory_df = pd.read_excel(excel_path, sheet_name="Inventory")
    recipes_df = pd.read_excel(excel_path, sheet_name="Recipes")
    recipe_ingredients_df = pd.read_excel(excel_path, sheet_name="Recipe_Ingredients")

    prefs = preferences or {}
    dislikes = set(_standardize_name(x) for x in prefs.get("dislikes", []))
    food_type = str(prefs.get("food_type", "vegetarian")).lower()

    recipe_pool = recipes_df.copy()
    if meal_type != "Any":
        recipe_pool = recipe_pool[recipe_pool["Meal_Type"].astype(str).str.contains(meal_type, case=False, na=False)]

    available, unavailable = [], []
    for _, recipe in recipe_pool.iterrows():
        result = _match_recipe(recipe, recipe_ingredients_df, inventory_df, members)
        recipe_ing = recipe_ingredients_df[recipe_ingredients_df["Recipe_ID"] == recipe["Recipe_ID"]]
        ing_names = {_standardize_name(x) for x in recipe_ing["Ingredient_Name"].tolist()}

        if dislikes.intersection(ing_names):
            continue
        if food_type == "vegetarian" and ing_names.intersection({"chicken","egg","fish","mutton","prawn"}):
            continue

        if result["status"] in {"Available","Partially Available"}:
            available.append(result)
        else:
            unavailable.append(result)

    available.sort(key=lambda x: (0 if x["status"] == "Available" else 1, x["total_time_min"]))
    unavailable.sort(key=lambda x: x["recipe_name"])

    time_limit = _recommend_limit(workload_level, stress_score)

    if meal_type.lower() == "dinner":
        recommended = _dinner_recommendations(available, workload_level, stress_score)
    else:
        recommended = _diversify_recommendations(available, time_limit, meal_type)

    for item in recommended:
        item["one_liner"] = f"{item['recipe_name']} • {item['meal_type']} • {item['total_time_min']} min • {item['status']}"
        item["reason_line"] = _reason_line(item, workload_level, stress_score, context_label=context_label)

    low_stock_items = inventory_df[inventory_df["Status"].astype(str).str.lower().isin(["low stock","out of stock"])]["Item_Name"].tolist()
    suggested_purchase = []
    for item in unavailable:
        for reason in item["missing_mandatory"]:
            ingredient = reason.split(":")[0]
            if ingredient not in suggested_purchase:
                suggested_purchase.append(ingredient)

    reason_prefix = "evening" if meal_type.lower() == "dinner" else "current"
    return {
        "meal_type": meal_type,
        "members": members,
        "recommended_meals": recommended,
        "available_meals": available,
        "unavailable_meals": unavailable,
        "low_stock_items": low_stock_items,
        "suggested_purchase_items": suggested_purchase,
        "recommendation_reason": f"Selected based on {reason_prefix} {workload_level.lower()} and approx {time_limit} min cooking threshold.",
    }

def apply_recipe_to_inventory(excel_path: str, recipe_name: str, members: int = 2) -> Dict:
    inventory_df = pd.read_excel(excel_path, sheet_name="Inventory")
    recipes_df = pd.read_excel(excel_path, sheet_name="Recipes")
    recipe_ingredients_df = pd.read_excel(excel_path, sheet_name="Recipe_Ingredients")

    matched = recipes_df[recipes_df["Recipe_Name"].astype(str).str.lower() == recipe_name.strip().lower()]
    if matched.empty:
        return {"status": "error", "message": f"Recipe not found: {recipe_name}"}

    recipe_row = matched.iloc[0]
    ingredients = _recipe_ingredients(recipe_row["Recipe_ID"], recipe_ingredients_df, members)

    updates: List[Dict] = []

    for _, ing in ingredients.iterrows():
        row = inventory_df["Item_Name"].astype(str).str.lower() == ing["Ingredient_Name"].strip().lower()
        if not row.any():
            continue

        current_qty = float(inventory_df.loc[row, "Quantity_Available"].iloc[0])
        new_qty = max(0.0, current_qty - float(ing["Required_Qty"]))
        min_stock = float(inventory_df.loc[row, "Minimum_Stock"].iloc[0]) if pd.notna(inventory_df.loc[row, "Minimum_Stock"].iloc[0]) else 0.0
        status = "Out of Stock" if new_qty <= 0 else "Low Stock" if new_qty <= min_stock else "Available"

        inventory_df.loc[row, "Quantity_Available"] = new_qty
        inventory_df.loc[row, "Status"] = status
        updates.append({
            "ingredient": ing["Ingredient_Name"],
            "used_qty": float(ing["Required_Qty"]),
            "remaining_qty": new_qty,
            "status": status
        })

    with pd.ExcelWriter(excel_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        inventory_df.to_excel(writer, sheet_name="Inventory", index=False)

    return {"status": "success", "recipe_name": recipe_row["Recipe_Name"], "members": members, "updates": updates}
