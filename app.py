from typing import List, Tuple
import html

import streamlit as st
import streamlit.components.v1 as components
from keep_export import create_keep_list_note
from urllib.parse import quote

from scraper import Recipe, fetch_recipe, combine_ingredients

st.set_page_config(page_title="Weekly Meal Planner", page_icon="🛒", layout="wide")

st.title("🛒 Weekly Meal Planner + Grocery List")
st.caption("Add recipe URLs on the left and build a grocery list on the right.")

st.markdown(
    """
    <style>
    .stMarkdown p, .stMarkdown div {
        margin: 0;
        line-height: 1.0;
    }

    div[data-testid="stCheckbox"] {
        display: flex;
        align-items: center;
        height: 32px;
    }

    div[data-testid="stCheckbox"] > label {
        display: flex;
        align-items: center;
        margin: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "recipe_cards" not in st.session_state:
    st.session_state.recipe_cards = [{"id": 1, "url": ""}]

if "next_card_id" not in st.session_state:
    st.session_state.next_card_id = 2

if "grocery_rows" not in st.session_state:
    st.session_state.grocery_rows = []

if "loaded_recipe_titles" not in st.session_state:
    st.session_state.loaded_recipe_titles = []

if "failed_urls" not in st.session_state:
    st.session_state.failed_urls = []

def build_keep_items(rows: List[dict]) -> List[str]:
    items = []
    for row in rows:
        quantity = row["Quantity"].strip()
        item = row["Item"].strip()
        if quantity:
            items.append(f"{quantity} {item}")
        else:
            items.append(item)
    return items

def build_sms_text(rows: List[dict]) -> str:
    lines = ["Weekly Grocery List", ""]

    current_category = None
    for row in rows:
        if row["Category"] != current_category:
            current_category = row["Category"]
            lines.append(current_category)

        quantity = row["Quantity"].strip()
        item = row["Item"].strip()

        if quantity:
            lines.append(f"- {quantity} {item}")
        else:
            lines.append(f"- {item}")

    return "\n".join(lines)

def add_recipe_card() -> None:
    st.session_state.recipe_cards.append(
        {"id": st.session_state.next_card_id, "url": ""}
    )
    st.session_state.next_card_id += 1


def remove_recipe_card(card_id: int) -> None:
    st.session_state.recipe_cards = [
        card for card in st.session_state.recipe_cards if card["id"] != card_id
    ]
    if not st.session_state.recipe_cards:
        add_recipe_card()


def format_quantity(qty) -> str:
    if qty is None:
        return ""
    if float(qty).is_integer():
        return str(int(qty))
    return f"{qty:.2f}".rstrip("0").rstrip(".")


def build_list_rows(recipes: List[Recipe]) -> List[dict]:
    combined = combine_ingredients(recipes)
    rows = []

    for ingredient in sorted(
        combined.values(), key=lambda item: (item.category, item.name)
    ):
        quantity_text = " ".join(
            part
            for part in [format_quantity(ingredient.quantity), ingredient.unit or ""]
            if part
        ).strip()

        rows.append(
            {
                "Category": ingredient.category,
                "Quantity": quantity_text,
                "Item": ingredient.name.title(),
            }
        )

    return rows


def build_ourgroceries_text(rows: List[dict]) -> str:
    lines = []
    for row in rows:
        quantity = row["Quantity"].strip()
        item = row["Item"].strip()
        if quantity:
            lines.append(f"{item} ({quantity})")
        else:
            lines.append(item)
    return "\n".join(lines)


left_col, right_col = st.columns([1, 1.1], gap="large")

with left_col:
    st.subheader("📋 Recipes for the Week")
    st.write("Paste recipe URLs below. Recipe names will be pulled in automatically.")

    st.button("➕ Add Recipe Card", on_click=add_recipe_card, use_container_width=True)

    recipe_inputs = []

    for index, card in enumerate(st.session_state.recipe_cards):
        card_id = card["id"]

        with st.container(border=True):
            top_left, top_right = st.columns([6, 1])

            with top_left:
                st.markdown(f"**Recipe {index + 1}**")

            with top_right:
                st.button(
                    "✕",
                    key=f"remove_{card_id}",
                    on_click=remove_recipe_card,
                    args=(card_id,),
                )

            url = st.text_input(
                "Recipe URL",
                value=card["url"],
                placeholder="https://craftavenue.com/recipe-name/",
                key=f"url_{card_id}",
            )

            recipe_inputs.append({"id": card_id, "url": url.strip()})

    if st.button("🧾 Build Grocery List", type="primary", use_container_width=True):
        valid_inputs = [r for r in recipe_inputs if r["url"]]

        if not valid_inputs:
            st.warning("Please add at least one recipe URL.")
        else:
            recipes: List[Recipe] = []
            failed_urls: List[Tuple[str, str]] = []
            loaded_titles: List[str] = []

            progress = st.progress(0)
            status = st.empty()

            for index, recipe_input in enumerate(valid_inputs, start=1):
                url = recipe_input["url"]
                status.write(f"Loading recipe {index} of {len(valid_inputs)}")

                try:
                    recipe = fetch_recipe(url)
                    recipes.append(recipe)
                    loaded_titles.append(recipe.title)
                except Exception as e:
                    failed_urls.append((url, str(e)))

                progress.progress(index / len(valid_inputs))

            status.empty()
            progress.empty()

            st.session_state.loaded_recipe_titles = loaded_titles
            st.session_state.failed_urls = failed_urls
            st.session_state.grocery_rows = build_list_rows(recipes) if recipes else []

            for key in list(st.session_state.keys()):
                if key.startswith("checked_"):
                    del st.session_state[key]

    if st.session_state.loaded_recipe_titles:
        st.markdown("### Loaded Recipes")
        for title in st.session_state.loaded_recipe_titles:
            st.success(title)

    if st.session_state.failed_urls:
        st.markdown("### Failed to Load")
        for url, error in st.session_state.failed_urls:
            st.error(f"{url}\n\n{error}")

with right_col:

    st.subheader("🛍️ Grocery List")
    st.write("Your combined grocery list will appear here.")

    if st.session_state.grocery_rows:
        current_category = None

        for row_index, row in enumerate(st.session_state.grocery_rows):
            if row["Category"] != current_category:
                current_category = row["Category"]
                st.markdown(
                    f"<div style='font-size:16px; font-weight:600; margin:10px 0 6px 0;'>{current_category}</div>",
                    unsafe_allow_html=True,
                )

            checked = st.session_state.get(f"checked_{row_index}", False)
            item_opacity = "0.45" if checked else "1.0"

            row_cols = st.columns([0.12, 0.28, 0.60], vertical_alignment="center")

            with row_cols[0]:
                st.checkbox(
                    "",
                    key=f"checked_{row_index}",
                    label_visibility="collapsed",
                )

            with row_cols[1]:
                st.markdown(
                    f"<div style='font-size:13px; font-weight:600; color:#333; opacity:{item_opacity};'>{row['Quantity'] or '-'}</div>",
                    unsafe_allow_html=True,
                )

            with row_cols[2]:
                st.markdown(
                    f"<div style='font-size:14px; color:#333; opacity:{item_opacity};'>{row['Item']}</div>",
                    unsafe_allow_html=True,
                )

        if st.button("🗑 Remove Checked Items", use_container_width=True):
            new_rows = []
            for i, row in enumerate(st.session_state.grocery_rows):
                if not st.session_state.get(f"checked_{i}", False):
                    new_rows.append(row)

            st.session_state.grocery_rows = new_rows

            for key in list(st.session_state.keys()):
                if key.startswith("checked_"):
                    del st.session_state[key]

            st.rerun()

        ourgroceries_text = build_ourgroceries_text(st.session_state.grocery_rows)

        st.markdown("### Copy to OurGroceries")
        st.caption(
            "Paste this into OurGroceries → open a shopping list → menu → Import items."
        )

        st.text_area(
            "OurGroceries Import Text",
            value=ourgroceries_text,
            height=180,
            key="ourgroceries_export",
            help="Each item is on its own line for easy import into OurGroceries.",
        )

        safe_copy_text = html.escape(ourgroceries_text)

        copy_html = f"""
        <div style="margin-top: 0.5rem;">
            <button
                onclick="navigator.clipboard.writeText(document.getElementById('ourgroceries_copy_source').innerText)"
                style="
                    background-color:#f0f2f6;
                    border:1px solid #d0d4db;
                    border-radius:8px;
                    padding:8px 14px;
                    cursor:pointer;
                    font-size:14px;
                "
            >Copy OurGroceries Text</button>
            <pre id="ourgroceries_copy_source" style="display:none;">{safe_copy_text}</pre>
        </div>
        """
        components.html(copy_html, height=50)
    else:
        st.info("Build a grocery list from the recipe cards on the left.")


#    if st.button("📝 Send to Google Keep", use_container_width=True):
#        try:
#            keep_items = build_keep_items(st.session_state.grocery_rows)
#            note = create_keep_list_note(
#                title="Weekly Grocery List",
#                items=keep_items,
#            )
#            st.success(f"Sent to Google Keep: {note.get('title', 'Weekly Grocery List')}")
#        except Exception as e:
#            st.error(f"Google Keep export failed: {e}")

    sms_text = build_sms_text(st.session_state.grocery_rows)
    encoded_sms_text = quote(sms_text)

    st.markdown("### Text This List")
    st.caption("This opens your texting app with the grocery list filled in.")

    phone_number = st.text_input(
        "Phone Number (optional)",
        placeholder="5551234567",
        key="sms_phone_number",
        help="Leave blank to just open your texting app. Add a number to prefill the recipient.",
    ).strip()

    sms_link = f"sms:{phone_number}?body={encoded_sms_text}" if phone_number else f"sms:?body={encoded_sms_text}"

    st.link_button(
        "Open Text Message",
        sms_link,
        use_container_width=True,
    )