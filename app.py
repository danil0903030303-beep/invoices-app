import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
import os
import urllib.request
from fpdf import FPDF
from datetime import datetime
import textwrap

st.title("Генератор зведеної видаткової (PDF)")

# Автоматичне завантаження шрифту
@st.cache_resource
def get_font():
    font_path = "Roboto-Regular.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf"
        urllib.request.urlretrieve(url, font_path)
    return font_path

# Завантаження файлів
uploaded_files = st.file_uploader("Перетягніть PDF-рахунки сюди", type="pdf", accept_multiple_files=True)

if uploaded_files:
    if st.button("Сформувати 1 видаткову"):
        all_items = []
        
        for file in uploaded_files:
            with pdfplumber.open(file) as pdf_file:
                for page in pdf_file.pages:
                    table = page.extract_table()
                    
                    if table:
                        for row in table:
                            clean_row = [str(cell).strip() if cell is not None else "" for cell in row]
                            
                            # Шукаємо рядки з товарами
                            if len(clean_row) >= 5 and clean_row[0].isdigit():
                                article = clean_row[1]
                                item_name = clean_row[2]
                                
                                sum_str = clean_row[-1]
                                price_str = clean_row[-2]
                                qty_str = clean_row[3] 
                                
                                try:
                                    qty = float(re.sub(r'[^\d.,]', '', qty_str).replace(',', '.'))
                                    price = float(re.sub(r'[^\d.,]', '', price_str).replace(',', '.'))
                                    total_sum = float(re.sub(r'[^\d.,]', '', sum_str).replace(',', '.'))
                                    
                                    all_items.append({
                                        "Артикул": article,
                                        "Товар": item_name,
                                        "Кількість": qty,
                                        "Ціна": price,
                                        "Сума": total_sum
                                    })
                                except ValueError:
                                    continue

        if all_items:
            df = pd.DataFrame(all_items)
            summary_df = df.groupby(["Артикул", "Товар"], as_index=False).agg({"Кількість": "sum", "Сума": "sum"})
            summary_df["Ціна"] = (summary_df["Сума"] / summary_df["Кількість"]).round(2)
            
            # --- ГЕНЕРАЦІЯ PDF ---
            pdf = FPDF()
            pdf.add_page()
            font_path = get_font()
            pdf.add_font("Roboto", "", font_path, uni=True)
            
            # Заголовок
            pdf.set_font("Roboto", size=14)
            months = {"January": "січня", "February": "лютого", "March": "березня", "April": "квітня", "May": "травня", "June": "червня", "July": "липня", "August": "серпня", "September": "вересня", "October": "жовтня", "November": "листопада", "December": "грудня"}
            current_date_eng = datetime.now().strftime("%d %B %Y")
            for eng, ukr in months.items():
                current_date_eng = current_date_eng.replace(eng, ukr)
            
            pdf.cell(0, 10, txt=f"Видаткова накладна від {current_date_eng} р.", ln=True, align='L')
            pdf.ln(5)
            
            # Реквізити
            pdf.set_font("Roboto", size=10)
            
            # Постачальник
            x = pdf.get_x()
            y = pdf.get_y()
            pdf.cell(35, 6, txt="Постачальник:", border=0)
            pdf.set_xy(x + 35, y)
            
            supplier_text = (
                "ФОП Гуменюк П.В. ЄДРПОУ 3516808797 ІПН 3516808797\n"
                "Юридична адреса: 30100, Хмельницька обл., м. Нетішин, вулиця Енергетиків буд. 1 кв. 64,\n"
                "р/р UA393052990000026000036007939 у банку ПАТ \"ПРИВАТБАНК\", м. Хмельницький, тел. +380962117164"
            )
            pdf.multi_cell(0, 6, txt=supplier_text, border=0)
            pdf.ln(2)
            
            # Покупець
            x = pdf.get_x()
            y = pdf.get_y()
            pdf.cell(35, 6, txt="Покупець:", border=0)
            pdf.set_xy(x + 35, y)
            pdf.multi_cell(0, 6, txt="ТОВ Технології Поля", border=0)
            pdf.ln(8)
            
            # Шапка таблиці
            col_widths = [10, 20, 100, 20, 20, 20]
            headers = ["№", "Артикул", "Товар", "Кількість", "Ціна", "Сума"]
            for i in range(len(headers)):
                pdf.cell(col_widths[i], 8, txt=headers[i], border=1, align='C')
            pdf.ln()
            
            # Наповнення таблиці
            total_invoice_sum = 0
            for idx, row in summary_df.iterrows():
                item_name = str(row['Товар'])
                
                # Розбиваємо текст на рядки (ширина 45 символів)
                wrapped_name = textwrap.fill(item_name, width=45)
                lines_count = len(wrapped_name.split('\n'))
                
                # Визначаємо висоту рядка
                line_height_for_multi = 6
                if lines_count == 1:
                    row_height = 8
                    line_height_for_multi = 8
                else:
                    row_height = line_height_for_multi * lines_count
                
                # Фіксуємо початкову позицію
                x_start = pdf.get_x()
                y_start = pdf.get_y()
                
                pdf.cell(col_widths[0], row_height, txt=str(idx+1), border=1, align='C')
                pdf.cell(col_widths[1], row_height, txt=str(row['Артикул']), border=1, align='C')
                
                # Створюємо багаторядкову клітинку для "Товару"
                x_after_articul = pdf.get_x()
                pdf.multi_cell(col_widths[2], line_height_for_multi, txt=wrapped_name, border=1, align='L')
                
                # Повертаємо курсор на початок рядка для малювання наступних колонок
                pdf.set_xy(x_after_articul + col_widths[2], y_start)
                
                pdf.cell(col_widths[3], row_height, txt=f"{int(row['Кількість'])} шт", border=1, align='C')
                pdf.cell(col_widths[4], row_height, txt=f"{row['Ціна']:.2f}", border=1, align='C')
                pdf.cell(col_widths[5], row_height, txt=f"{row['Сума']:.2f}", border=1, align='C')
                
                # Переходимо на наступний рядок
                pdf.ln(row_height)
                total_invoice_sum += row['Сума']
            
            pdf.ln(5)
            
            # Підсумок
            pdf.set_font("Roboto", size=12)
            pdf.cell(0, 8, txt=f"Разом: {total_invoice_sum:.2f}", ln=True, align='R')
            
            pdf_bytes = bytes(pdf.output())
            
            st.success("PDF-накладну успішно згенеровано!")
            
            st.download_button(
                label="Завантажити видаткову (PDF)",
                data=pdf_bytes,
                file_name="Vydatkova_Zvedena.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("Не вдалося розпізнати товари. Перевірте формат рахунків.")