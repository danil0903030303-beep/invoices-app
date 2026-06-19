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

# --- ФУНКЦІЯ ДЛЯ СУМИ ПРОПИСОМ ---
def number_to_words_uah(amount):
    def get_words(num, is_female=False):
        units = ["", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять"]
        units_f = ["", "одна", "дві", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять"]
        teens = ["десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять", "дев'ятнадцять"]
        tens = ["", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят", "сімдесят", "вісімдесят", "дев'яносто"]
        hundreds = ["", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот", "вісімсот", "дев'ятсот"]

        words = []
        h = num // 100
        if h > 0: words.append(hundreds[h])
        rem = num % 100
        if 10 <= rem <= 19:
            words.append(teens[rem - 10])
        else:
            t = rem // 10
            u = rem % 10
            if t > 0: words.append(tens[t])
            if u > 0: words.append(units_f[u] if is_female else units[u])
        return words

    int_part = int(amount)
    kop = int(round((amount - int_part) * 100))

    if int_part == 0:
        words = ["нуль"]
    else:
        words = []
        m = int_part // 1000000
        if m > 0:
            words.extend(get_words(m))
            if m % 10 == 1 and m % 100 != 11: words.append("мільйон")
            elif 2 <= m % 10 <= 4 and not (12 <= m % 100 <= 14): words.append("мільйони")
            else: words.append("мільйонів")

        rem = int_part % 1000000
        th = rem // 1000
        if th > 0:
            words.extend(get_words(th, is_female=True))
            if th % 10 == 1 and th % 100 != 11: words.append("тисяча")
            elif 2 <= th % 10 <= 4 and not (12 <= th % 100 <= 14): words.append("тисячі")
            else: words.append("тисяч")

        u = rem % 1000
        if u > 0 or int_part == 0:
            words.extend(get_words(u, is_female=True))

    u100 = int_part % 100
    u10 = int_part % 10
    if u10 == 1 and u100 != 11:
        currency = "гривня"
    elif 2 <= u10 <= 4 and not (12 <= u100 <= 14):
        currency = "гривні"
    else:
        currency = "гривень"

    res = " ".join(words).strip()
    # Робимо першу букву великою, прибираємо зайві пробіли
    res = re.sub(' +', ' ', res).capitalize()
    return f"{res} {kop:02d} копійок"


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
            # Витягуємо номер рахунку з назви файлу (беремо лише цифри)
            invoice_num = re.sub(r'\D', '', file.name)
            if not invoice_num:
                invoice_num = file.name.split('.')[0] # Якщо цифр немає, беремо назву цілком

            with pdfplumber.open(file) as pdf_file:
                for page in pdf_file.pages:
                    # Стандартна спроба витягнути таблицю
                    table = page.extract_table()
                    
                    # Запасний план для рахунків без чітких ліній (як ваш 433947.pdf)
                    if not table:
                        table = page.extract_table(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"})
                    
                    if table:
                        for row in table:
                            clean_row = [str(cell).strip() if cell is not None else "" for cell in row]
                            
                            # Перевіряємо, чи це товар (перша колонка - число)
                            if len(clean_row) >= 5 and clean_row[0].replace('.', '').isdigit():
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
                                        "Рахунок": invoice_num,
                                        "Товар": item_name,
                                        "Кількість": qty,
                                        "Ціна": price,
                                        "Сума": total_sum
                                    })
                                except ValueError:
                                    continue

        if all_items:
            df = pd.DataFrame(all_items)
            
            # Зводимо дані. Якщо товар у кількох рахунках, номери рахунків об'єднаються через кому
            summary_df = df.groupby(["Артикул", "Товар"], as_index=False).agg({
                "Рахунок": lambda x: ", ".join(sorted(set(str(v) for v in x if v))),
                "Кількість": "sum",
                "Сума": "sum"
            })
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
            
            pdf.cell(0, 10, txt=f"Видаткова накладна № ЗВЕДЕНА від {current_date_eng} р.", ln=True, align='L')
            pdf.ln(5)
            
            # Реквізити
            pdf.set_font("Roboto", size=10)
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
            
            x = pdf.get_x()
            y = pdf.get_y()
            pdf.cell(35, 6, txt="Покупець:", border=0)
            pdf.set_xy(x + 35, y)
            pdf.multi_cell(0, 6, txt="ТОВ Технології Поля", border=0)
            pdf.ln(8)
            
            # Шапка таблиці (оновлені ширини під нову колонку)
            col_widths = [10, 18, 18, 84, 20, 20, 20]
            headers = ["№", "Артикул", "Рахунок", "Товар", "Кількість", "Ціна", "Сума"]
            for i in range(len(headers)):
                pdf.cell(col_widths[i], 8, txt=headers[i], border=1, align='C')
            pdf.ln()
            
            # Наповнення таблиці
            total_invoice_sum = 0
            for idx, row in summary_df.iterrows():
                item_name = str(row['Товар'])
                wrapped_name = textwrap.fill(item_name, width=42) # Трохи зменшили ширину тексту під колонку
                lines_count = len(wrapped_name.split('\n'))
                
                line_height_for_multi = 6
                if lines_count == 1:
                    row_height = 8
                    line_height_for_multi = 8
                else:
                    row_height = line_height_for_multi * lines_count
                
                x_start = pdf.get_x()
                y_start = pdf.get_y()
                
                pdf.cell(col_widths[0], row_height, txt=str(idx+1), border=1, align='C')
                pdf.cell(col_widths[1], row_height, txt=str(row['Артикул']), border=1, align='C')
                
                # Колонка Рахунок
                pdf.cell(col_widths[2], row_height, txt=str(row['Рахунок']), border=1, align='C')
                
                x_after_account = pdf.get_x()
                pdf.multi_cell(col_widths[3], line_height_for_multi, txt=wrapped_name, border=1, align='L')
                
                pdf.set_xy(x_after_account + col_widths[3], y_start)
                
                pdf.cell(col_widths[4], row_height, txt=f"{int(row['Кількість'])} шт", border=1, align='C')
                pdf.cell(col_widths[5], row_height, txt=f"{row['Ціна']:.2f}", border=1, align='C')
                pdf.cell(col_widths[6], row_height, txt=f"{row['Сума']:.2f}", border=1, align='C')
                
                pdf.ln(row_height)
                total_invoice_sum += row['Сума']
            
            pdf.ln(5)
            
            # Підсумок "Разом"
            pdf.set_font("Roboto", size=11, style='B') # Жирний шрифт для підсумку
            pdf.cell(0, 8, txt=f"Разом: {total_invoice_sum:.2f}", ln=True, align='R')
            pdf.ln(2)
            
            # Всього найменувань і сума прописом
            pdf.set_font("Roboto", size=10)
            pdf.cell(0, 6, txt=f"Всього найменувань {len(summary_df)}, на суму {total_invoice_sum:.2f} грн", ln=True, align='L')
            
            sum_words = number_to_words_uah(total_invoice_sum)
            pdf.set_font("Roboto", size=10, style='B')
            pdf.cell(0, 6, txt=sum_words, ln=True, align='L')
            pdf.ln(15)
            
            # Підписи
            pdf.set_font("Roboto", size=10, style='B')
            x_sig = pdf.get_x()
            y_sig = pdf.get_y()
            pdf.cell(90, 10, txt="Від виконавця  ________________________", border=0, align='L')
            pdf.set_xy(x_sig + 90, y_sig)
            pdf.cell(100, 10, txt="Отримав(ла)  ________________________", border=0, align='R')
            
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
