
import json
import os
from statistics import mean

def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def update_habit_memory(memory_path: str, entry: dict):
    memory = load_json_file(memory_path, {"recipe_profiles": {}, "meal_slot_patterns": {}, "summary_notes": []})
    recipe = (entry.get("recipe_name") or "").strip()
    members = entry.get("members", 2)
    meal_slot = (entry.get("meal_slot") or "Any").strip()
    made_recipe = bool(entry.get("made_recipe", False))
    custom_cooked = (entry.get("custom_cooked") or "").strip()
    actual_time = entry.get("actual_time_min")

    if made_recipe and recipe:
        prof = memory["recipe_profiles"].setdefault(recipe, {
            "times_taken": [],
            "made_count": 0,
            "last_members": members,
            "avg_time_min": None,
            "preferred_slots": [],
        })
        prof["made_count"] += 1
        prof["last_members"] = members
        if actual_time is not None:
            prof["times_taken"].append(actual_time)
            prof["avg_time_min"] = round(mean(prof["times_taken"]), 1)
        if meal_slot and meal_slot not in prof["preferred_slots"]:
            prof["preferred_slots"].append(meal_slot)

    if meal_slot:
        slot = memory["meal_slot_patterns"].setdefault(meal_slot, {"made_recipes": {}, "custom_cooked": {}})
        if made_recipe and recipe:
            slot["made_recipes"][recipe] = slot["made_recipes"].get(recipe, 0) + 1
        elif custom_cooked:
            slot["custom_cooked"][custom_cooked] = slot["custom_cooked"].get(custom_cooked, 0) + 1

    notes = []
    if recipe and made_recipe and actual_time is not None:
        notes.append(f"User made {recipe} in about {actual_time} minutes.")
    if custom_cooked:
        notes.append(f"Instead of the suggested meal, user cooked {custom_cooked} for {meal_slot}.")
    if notes:
        memory["summary_notes"] = (memory.get("summary_notes", []) + notes)[-30:]

    save_json_file(memory_path, memory)
    return memory

def get_habit_memory(memory_path: str):
    memory = load_json_file(memory_path, {"recipe_profiles": {}, "meal_slot_patterns": {}, "summary_notes": []})
    recipe_profiles = memory.get("recipe_profiles", {})
    fastest = []
    for name, prof in recipe_profiles.items():
        if prof.get("avg_time_min") is not None:
            fastest.append({"recipe_name": name, "avg_time_min": prof["avg_time_min"], "made_count": prof.get("made_count", 0)})
    fastest = sorted(fastest, key=lambda x: x["avg_time_min"])[:5]

    slot_patterns = {}
    for slot, details in memory.get("meal_slot_patterns", {}).items():
        made = details.get("made_recipes", {})
        custom = details.get("custom_cooked", {})
        slot_patterns[slot] = {
            "top_made_recipes": sorted(made.items(), key=lambda x: x[1], reverse=True)[:3],
            "top_custom_meals": sorted(custom.items(), key=lambda x: x[1], reverse=True)[:3],
        }

    return {
        "fastest_recipes": fastest,
        "slot_patterns": slot_patterns,
        "summary_notes": memory.get("summary_notes", [])[-10:],
        "raw": memory,
    }
