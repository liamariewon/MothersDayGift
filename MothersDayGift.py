import re
import json
from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Tuple, Dict

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup


# ----------------------------
# Page setup
# ----------------------------

st.set_page_config(page_title="Recipe Grocery List Builder", page_icon="🛒", layout="wide")


# ----------------------------
# Models
# ----------------------------

@dataclass
class Ingredient:
    original: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    name: str = ""
    notes: Optional[str] = None
    category: str = "Other"


@dataclass
class Recipe:
    title: str
    url: str
    ingredients: List[Ingredient] = field(default_factory=list)


# ----------------------------
# Parsing helpers
# ----------------------------

FRACTION_MAP = {
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "⅐": "1/7",
    "⅑": "1/9",
    "⅒": "1/10",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

UNIT_ALIASES = {
    "cup": "cup",
    "cups": "cup",
    "c": "cup",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tbsp": "tbsp",
    "tbs": "tbsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tsp": "tsp",
    "pound": "lb",
    "pounds": "lb",
    "lb": "lb",
    "lbs": "lb",
    "ounce": "oz",
    "ounces": "oz",
    "oz": "oz",
    "clove": "clove",
    "cloves": "clove",
    "medium": "medium",
    "large": "large",
    "small": "small",
    "can": "can",
    "cans": "can",
    "package": "package",
    "packages": "package",
    "pkg": "package",
}

NAME_NORMALIZATION = {
    "fresh mushrooms": "mushrooms",
    "mushrooms": "mushrooms",
    "medium onions": "onions",
    "onions": "onions",
    "yellow onion": "onions",
    "yellow onions": "onions",
    "white onion": "onions",
    "white onions": "onions",
    "garlic clove": "garlic",
    "garlic cloves": "garlic",
    "all-purpose flour": "flour",
    "beef broth": "beef broth",
    "chicken broth": "chicken broth",
    "vegetable broth": "vegetable broth",
    "beef sirloin steak": "beef sirloin steak",
    "sour cream": "sour cream",
    "hot cooked egg noodles": "egg noodles",
    "egg noodles": "egg noodles",
    "worcestershire sauce": "worcestershire sauce",
    "butter": "butter",
    "salt": "salt",
    "black pepper": "black pepper",
}

CATEGORY_KEYWORDS = {
    "Produce": ["garlic", "onion", "onions", "mushroom", "mushrooms", "pepper", "lemon", "lime", "parsley", "cilantro", "spinach", "tomato", "tomatoes"],
    "Meat": ["beef", "chicken", "turkey", "pork", "steak", "sausage", "bacon"],
    "Dairy": ["milk", "butter", "sour cream", "cream cheese", "cheese", "yogurt", "heavy cream"],
    "Pasta & Grains": ["rice", "pasta", "egg noodles", "bread", "flour", "oats", "quinoa", "couscous"],
    "Canned & Broth": ["broth", "stock", "beans", "tomato sauce", "tomatoes", "can"],
    "Spices & Pantry": ["salt", "pepper", "paprika", "oregano", "basil", "oil", "vinegar", "sugar", "worcestershire sauce"],
}


def normalize_fraction_text(text: str) -> str:
    for symbol, replacement in FRACTION_MAP.items():
        text = text.replace(symbol, replacement)
    return text



def parse_quantity_token(token: str) -> Optional[float]:
    token = token.strip()
    if not token:
        return None

    if " " in token:
        parts = token.split()
        try:
            return float(sum(Fraction(p) for p in parts))
        except Exception:
            pass

    try:
        return float(Fraction(token))
    except Exception:
        pass

    try:
        return float(token)
    except Exception:
        return None



def categorize_ingredient(name: str) -> str:
    lowered = name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Other"



def parse_ingredient_line(line: str) -> Ingredient:
    original = line.strip()
    text = normalize_fraction_text(original)
    text = re.sub(r"\s+", " ", text).strip()

    pattern = re.compile(
        r"^(?P<qty>\d+(?:/\d+)?(?: \d+(?:/\d+)?)?)?\s*"
        r"(?P<unit>[A-Za-z]+)?\s*"
        r"(?P<name>.*)$"
    )

    match = pattern.match(text)
    if not match:
        return Ingredient(original=original, name=original, category="Other")

    qty_str = (match.group("qty") or "").strip()
    unit_str = (match.group("unit") or "").strip().lower()
    name_str = (match.group("name") or "").strip(" ,")

    quantity = parse_quantity_token(qty_str) if qty_str else None
    unit = UNIT_ALIASES.get(unit_str)

    if unit in {"small", "medium", "large"}:
        if name_str:
            name_str = f"{unit} {name_str}"
        unit = None

    notes = None
    split_match = re.split(r",|\(|\bfinely\b|\bthinly\b|\bsliced\b|\bchopped\b|\bcooked\b", name_str, maxsplit=1, flags=re.IGNORECASE)
    if split_match:
        clean_name = split_match[0].strip()
        if clean_name != name_str:
            notes = name_str[len(clean_name):].strip(" ,") or None
        name_str = clean_name

    normalized_name = NAME_NORMALIZATION.get(name_str.lower(), name_str.lower())
    category = categorize_ingredient(normalized_name)

    return Ingredient(
        original=original,
        quantity=quantity,
        unit=unit,
        name=normalized_name,
        notes=notes,
        category=category,
    )


# ----------------------------
# Recipe extraction
# ----------------------------


def extract_recipe_from_json_ld(html: str, url: str) -> Recipe:
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        raw_text = script.string or script.get_text(strip=True)
        if not raw_text:
            continue
        try:
            data = json.loads(raw_text)
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            recipe_obj = find_recipe_object(item)
            if recipe_obj:
                title = recipe_obj.get("name", "Recipe")
                ingredient_lines = recipe_obj.get("recipeIngredient", [])
                ingredients = [parse_ingredient_line(line) for line in ingredient_lines]
                return Recipe(title=title, url=url, ingredients=ingredients)

    raise ValueError("No recipe JSON-LD found on page")



def find_recipe_object(obj):
    if isinstance(obj, dict):
        obj_type = obj.get("@type")
        if obj_type == "Recipe" or (isinstance(obj_type, list) and "Recipe" in obj_type):
            return obj
        for value in obj.values():
            found = find_recipe_object(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_recipe_object(item)
            if found:
                return found
    return None



def fetch_recipe(url: str) -> Recipe:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")

    return extract_recipe_from_json_ld(response.text, url)


# ----------------------------
# Grocery list aggregation
# ----------------------------


def ingredient_key(ingredient: Ingredient) -> Tuple[str, Optional[str]]:
    return ingredient.name, ingredient.unit



def combine_ingredients(recipes: List[Recipe]) -> Dict[Tuple[str, Optional[str]], Ingredient]:
    combined: Dict[Tuple[str, Optional[str]], Ingredient] = {}

    for recipe in recipes:
        for ingredient in recipe.ingredients:
            key = ingredient_key(ingredient)
            if key not in combined:
                combined[key] = Ingredient(
                    original=ingredient.original,
                    quantity=ingredient.quantity,
                    unit=ingredient.unit,
                    name=ingredient.name,
                    notes=ingredient.notes,
                    category=ingredient.category,
                )
            else:
                existing = combined[key]
                if existing.quantity is not None and ingredient.quantity is not None:
                    existing.quantity += ingredient.quantity
                elif existing.quantity is None:
                    existing.quantity = ingredient.quantity

    return combined



def format_quantity(qty: Optional[float]) -> str:
    if qty is None:
        return ""
    if float(qty).is_integer():
        return str(int(qty))
    return f"{qty:.2f}".rstrip("0").rstrip(".")



def grocery_list_to_dataframe(combined: Dict[Tuple[str, Optional[str]], Ingredient]) -> pd.DataFrame:
    rows = []
    for ingredient in sorted(combined.values(), key=lambda item: (item.category, item.name)):
        rows.append(
            {
                "Done": False,
                "Category": ingredient.category,
                "Item": ingredient.name.title(),
                "Quantity": format_quantity(ingredient.quantity),
                "Unit": ingredient.unit or "",
                "Notes": ingredient.notes or "",
            }
        )
    return pd.DataFrame(rows)


# ----------------------------
# UI
# ----------------------------

st.title("🛒 Recipe Grocery List Builder")
st.caption("Paste recipe links, combine ingredients, and export an editable grocery list.")

with st.sidebar:
    st.header("How to use")
    st.write("1. Paste one recipe URL per line.")
    st.write("2. Click **Build Grocery List**.")
    st.write("3. Review and edit the grocery list.")
    st.write("4. Download it as a CSV file.")

    st.subheader("Install once")
    st.code("pip install streamlit requests beautifulsoup4 pandas")

    st.subheader("Run app")
    st.code("streamlit run your_file_name.py")

example_urls = """https://craftavenue.com/beef-stroganoff/"""

url_text = st.text_area(
    "Recipe URLs",
    value=example_urls,
    height=180,
    help="Add one recipe page per line.",
)

build_button = st.button("Build Grocery List", type="primary", use_container_width=True)

if build_button:
    urls = [line.strip() for line in url_text.splitlines() if line.strip()]

    if not urls:
        st.warning("Please enter at least one recipe URL.")
    else:
        recipes: List[Recipe] = []
        failed_urls: List[Tuple[str, str]] = []

        progress = st.progress(0)
        status = st.empty()

        for index, url in enumerate(urls, start=1):
            status.write(f"Loading recipe {index} of {len(urls)}: {url}")
            try:
                recipe = fetch_recipe(url)
                recipes.append(recipe)
            except Exception as e:
                failed_urls.append((url, str(e)))
            progress.progress(index / len(urls))

        status.empty()
        progress.empty()

        if recipes:
            st.success(f"Loaded {len(recipes)} recipe(s).")

            with st.expander("Loaded recipes", expanded=True):
                for recipe in recipes:
                    st.markdown(f"**{recipe.title}**")
                    st.caption(recipe.url)

            combined = combine_ingredients(recipes)
            grocery_df = grocery_list_to_dataframe(combined)

            st.subheader("Editable Grocery List")
            edited_df = st.data_editor(
                grocery_df,
                use_container_width=True,
                num_rows="dynamic",
                hide_index=True,
                key="grocery_editor",
            )

            csv_data = edited_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download Grocery List CSV",
                data=csv_data,
                file_name="grocery_list.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if failed_urls:
            st.subheader("Failed URLs")
            for url, error in failed_urls:
                st.error(f"{url}\n\n{error}")

if not build_button:
    st.info("Enter recipe links above, then click **Build Grocery List**.")
