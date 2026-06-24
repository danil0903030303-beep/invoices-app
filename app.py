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
import pytesseract

st.set_page_config(layout="wide")
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
    res = re.sub(' +', ' ', res).capitalize()
    return f"{res} {kop:02d} копійок"

@st.cache_resource
def get_fonts():
    reg_path = "Roboto-Regular.ttf"
    bold_path = "Roboto-Bold.ttf"
    if not os.path.exists(reg_path):
        urllib.request.urlretrieve("https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf", reg_path)
    if not os.path.exists(bold_path):
        urllib.request.urlretrieve("https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf", bold_path)
    return reg_path, bold_path

# --- НОВИЙ АБСОЛЮТНИЙ ПАРСЕР РЯДКІВ (З ІГНОРУВАННЯМ СМІТТЯ) ---
def parse_text_block(text, invoice_num):
    items = []
    UNITS = {'шт', 'шт.', 'кг', 'л', 'м', 'уп', 'уп.', 'штуки', 'штук'}
    
    for line in text.split('\n'):
        line = line.replace('|', ' ').replace('_', ' ').replace('—', ' ').strip()
        line = re.sub(r'\s+', ' ', line)
        
        if not line or "разом" in line.lower() or "сума" in line.lower() or "всього" in line.lower():
            continue
            
        tokens = line.split()
        
        # Знаходимо всі слова, які містять хоча б одну цифру
        tokens_with_digits = [i for i, t in enumerate(tokens) if any(c.isdigit() for c in t)]
        if len(tokens_with_digits) < 3: # Мінімум: Артикул, Ціна, Сума
            continue
            
        first_digit_idx = tokens_with_digits[0]
        second_digit_idx = tokens_with_digits[1]
        
        art = ""
        # Визначаємо, чи перша цифра - це порядковий номер (1, 2, 3...) чи сам Артикул
        if re.match(r'^\d{1,3}$', tokens[first_digit_idx].replace('.', '')):
            # Якщо перша цифра коротка (номер), перевіряємо, чи є ще цифри до ціни/суми
            if second_digit_idx < len(tokens) - 2:
                art = tokens[second_digit_idx] # Беремо другу цифру як Артикул
                tokens = tokens[second_digit_idx + 1 :] # Відрізаємо все до артикулу (вкл. сміття)
            else:
                art = tokens[first_digit_idx] # Це і є Артикул
                tokens = tokens[first_digit_idx + 1 :]
        else:
            # Якщо перша цифра довга або з буквами (ТПUT-123) - це точно Артикул
            art = tokens[first_digit_idx]
            tokens = tokens[first_digit_idx + 1 :]
            
        # Склеюємо розірвані сканером копійки (напр. "222 00" -> "222.00")
        new_tokens = []
        i = 0
        while i < len(tokens):
            tok = tokens[i].replace('O', '0').replace('o', '0').replace(',', '.')
            if i < len(tokens) - 1:
                next_tok = tokens[i+1].replace('O', '0').replace('o', '0')
                if re.match(r'^\d+$', tok) and re.match(r'^\d{2}$', next_tok):
                    new_tokens.append(tok + "." + next_tok)
                    i += 2
                    continue
            new_tokens.append(tok)
            i += 1
            
        if len(new_tokens) < 2: continue
        
        # Читаємо числа з кінця рядка
        rev_tokens = list(reversed(new_tokens))
        numbers = []
        processed = 0

        for tok in rev_tokens:
            if tok.lower() in UNITS:
                processed += 1
                continue
            
            m = re.match(r'^([\d.]+)([а-яА-Яa-zA-Z.]+)$', tok)
            if m and m.group(2).lower() in UNITS:
                try:
                    numbers.append(float(m.group(1)))
                    processed += 1
                    continue
                except:
                    pass
                
            if re.match(r'^[\d.]+$', tok) and any(c.isdigit() for c in tok):
                if tok.count('.') <= 1:
                    try:
                        numbers.append(float(tok))
                        processed += 1
                        continue
                    except:
                        pass
                    
            if len(numbers) >= 2: break
            
        if len(numbers) < 2: continue
        
        total = numbers[0]
        price = numbers[1]
        qty = numbers[2] if len(numbers) >= 3 else 0.0
        
        if price <= 0 or total <= 0: continue
        
        # Математична автокорекція (виправляє баг OCR з "200 шт" і "44400 сума")
        if qty > 0:
            if abs((qty / 100) * price - total) < 0.1: qty = qty / 100
            elif abs(qty * price - (total / 100)) < 0.1: total = total / 100
            elif abs((qty / 100) * price - (total / 100)) < 0.1:
                qty = qty / 100; total = total / 100
            elif abs(qty * (price / 100) - (total / 100)) < 0.1:
                price = price / 100; total = total / 100
        else:
            qty = round(total / price, 2)
            
        if abs(qty * price - total) > 0.5: continue
        
        name_tokens = new_tokens[:-processed] if processed > 0 else new_tokens
        name = " ".join(name_tokens).strip()
        
        if name:
            items.append({
                "Артикул": art,
                "Рахунок": invoice_num,
                "Товар": name,
                "Кількість": qty,
                "Ціна": price,
                "Сума": total
            })
    return items

uploaded_files = st.file_uploader("Перетягніть PDF-рахунки сюди", type="pdf", accept_multiple_files=True)

if uploaded_files:
    if st.button("Сформувати 1 видаткову"):
        all_items = []
        debug_logs = {}
        invoice_dates = set()
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"Аналіз файлу: {file.name}...")
            file_bytes = file.read()
            invoice_num = re.sub(r'\D', '', file.name)
            if not invoice_num:
                invoice_num = file.name.split('.')[0]

            page_items = []
            extracted_raw_text = ""
            all_text_for_date = ""

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf_file:
                for page in pdf_file.pages:
                    page_text = page.extract_text() or ""
                    all_text_for_date += page_text + "\n"
                    extracted_raw_text += "--- ТЕКСТ СТОРІНКИ ---\n" + page_text + "\n"
                    
                    # 1. Пробуємо ідеальну таблицю
                    table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                    if not table:
                        table = page.extract_table({"vertical_strategy": "text", "horizontal_strategy": "lines"})
                        
                    if table:
                        full_table_text = ""
                        for row in table:
                            clean_row = [str(c).replace('\n', ' ').strip() for c in row if c is not None]
                            if clean_row:
                                full_table_text += " ".join(clean_row) + "\n"
                        extracted_raw_text += "--- ТАБЛИЦЯ ---\n" + full_table_text + "\n"
                        page_items.extend(parse_text_block(full_table_text, invoice_num))
                    
                    # 2. Якщо таблиця не дала товарів, пробуємо текст
                    if not page_items and page_text:
                        page_items.extend(parse_text_block(page_text, invoice_num))

                    # 3. Якщо і це не вийшло (це векторний малюнок), застосовуємо БРОНЕБІЙНИЙ OCR
                    if not page_items:
                        status_text.text(f"Файл {file.name} - складний малюнок. Вмикаю глибокий OCR сканер...")
                        try:
                            # Захоплюємо чорно-біле фото у високій якості
                            img = page.to_image(resolution=400).original.convert('L')
                            # Відсікаємо всі тіні і сірі лінії таблиць (робимо жорсткий трафарет)
                            img = img.point(lambda x: 0 if x < 200 else 255, '1')
                            
                            # psm 6 - читати просто рядками (ігнорувати колонки)
                            custom_config = r'--psm 6'
                            
                            try:
                                ocr_text = pytesseract.image_to_string(img, lang='ukr+eng', config=custom_config)
                            except Exception:
                                try:
                                    ocr_text = pytesseract.image_to_string(img, lang='ukr', config=custom_config)
                                except Exception:
                                    ocr_text = pytesseract.image_to_string(img, config=custom_config)
                                
                            extracted_raw_text += "--- ТЕКСТ З OCR СКАНЕРА ---\n" + ocr_text + "\n"
                            all_text_for_date += ocr_text + "\n"
                            page_items.extend(parse_text_block(ocr_text, invoice_num))
                            
                        except Exception as e:
                            pass
            
            # --- ПОШУК ДАТИ РАХУНКУ ---
            date_match = re.search(r'(\d{1,2}\s+(?:січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня)\s+\d{4}\s*(?:[рpРP]\.?)?)', all_text_for_date, re.IGNORECASE)
            if date_match:
                clean_date = re.sub(r'\s+', ' ', date_match.group(1)).strip()
                clean_date = clean_date.replace('p', 'р').replace('P', 'Р')
                if not clean_date.endswith('.') and clean_date.endswith('р'):
                    clean_date += '.'
                elif not clean_date.endswith('.') and not clean_date.endswith('р'):
                    clean_date += ' р.'
                invoice_dates.add(clean_date)
            else:
                date_match_num = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', all_text_for_date)
                if date_match_num:
                    d, m, y = date_match_num.groups()
                    months_ukr = {"01":"січня", "02":"лютого", "03":"березня", "04":"квітня", "05":"травня", "06":"червня", "07":"липня", "08":"серпня", "09":"вересня", "10":"жовтня", "11":"листопада", "12":"грудня"}
                    if m in months_ukr:
                        invoice_dates.add(f"{int(d)} {months_ukr[m]} {y} р.")

            debug_logs[file.name] = extracted_raw_text
            
            if page_items:
                all_items.extend(page_items)
            
            progress = (i + 1) / len(uploaded_files)
            progress_bar.progress(progress)

        status_text.empty()
        progress_bar.empty()

        if all_items:
            df = pd.DataFrame(all_items)
            
            unique_invoices_list = sorted(df["Рахунок"].unique().astype(str))
            unique_invoices_str = ", ".join(unique_invoices_list)
            file_name_out = f"Vydatkova_{'_'.join(unique_invoices_list)}.pdf"
            
            summary_df = df.groupby(["Артикул", "Товар"], as_index=False).agg({
                "Кількість": "sum",
                "Сума": "sum"
            })
            summary_df["Ціна"] = (summary_df["Сума"] / summary_df["Кількість"]).round(2)
            
            if invoice_dates:
                final_date_str = ", ".join(sorted(list(invoice_dates)))
            else:
                months = {"January": "січня", "February": "лютого", "March": "березня", "April": "квітня", "May": "травня", "June": "червня", "July": "липня", "August": "серпня", "September": "вересня", "October": "жовтня", "November": "листопада", "December": "грудня"}
                final_date_str = datetime.now().strftime("%d %B %Y")
                for eng, ukr in months.items():
                    final_date_str = final_date_str.replace(eng, ukr)
                final_date_str += " р."
            
            # --- ГЕНЕРАЦІЯ PDF ---
            pdf = FPDF()
            pdf.add_page()
            
            font_reg, font_bold = get_fonts()
            pdf.add_font("Roboto", "", font_reg, uni=True)
            pdf.add_font("Roboto", "B", font_bold, uni=True)
            
            pdf.set_font("Roboto", size=14)
            
            pdf.cell(0, 10, txt=f"Видаткова накладна № {unique_invoices_str} від {final_date_str}", ln=True, align='L')
            pdf.ln(5)
            
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
            
            col_widths = [10, 20, 100, 20, 20, 20]
            headers = ["№", "Артикул", "Товар", "Кількість", "Ціна", "Сума"]
            for i in range(len(headers)):
                pdf.cell(col_widths[i], 8, txt=headers[i], border=1, align='C')
            pdf.ln()
            
            total_invoice_sum = 0
            for idx, row in summary_df.iterrows():
                clean_articul = re.sub(r'\s+', ' ', str(row['Артикул'])).strip()
                if len(clean_articul) > 10:
                    clean_articul = clean_articul[:9] + "…"
                    
                clean_name = re.sub(r'\s+', ' ', str(row['Товар'])).strip()
                wrapped_name = textwrap.fill(clean_name, width=42, break_long_words=True)
                lines_count = len(wrapped_name.split('\n'))
                
                row_height = max(8, lines_count * 5 + 2)
                
                if pdf.get_y() + row_height > 270:
                    pdf.add_page()
                    for i in range(len(headers)):
                        pdf.cell(col_widths[i], 8, txt=headers[i], border=1, align='C')
                    pdf.ln()

                x = pdf.get_x()
                y = pdf.get_y()
                
                pdf.rect(x, y, col_widths[0], row_height)
                pdf.rect(x + sum(col_widths[:1]), y, col_widths[1], row_height)
                pdf.rect(x + sum(col_widths[:2]), y, col_widths[2], row_height)
                pdf.rect(x + sum(col_widths[:3]), y, col_widths[3], row_height)
                pdf.rect(x + sum(col_widths[:4]), y, col_widths[4], row_height)
                pdf.rect(x + sum(col_widths[:5]), y, col_widths[5], row_height)
                
                y_center = y + (row_height - 6) / 2
                
                pdf.set_xy(x, y_center)
                pdf.cell(col_widths[0], 6, txt=str(idx+1), border=0, align='C')
                
                pdf.set_xy(x + sum(col_widths[:1]), y_center)
                pdf.cell(col_widths[1], 6, txt=clean_articul, border=0, align='C')
                
                pdf.set_xy(x + sum(col_widths[:2]) + 1, y + 1)
                pdf.multi_cell(col_widths[2] - 2, 5, txt=wrapped_name, border=0, align='L')
                
                pdf.set_xy(x + sum(col_widths[:3]), y_center)
                pdf.cell(col_widths[3], 6, txt=f"{int(row['Кількість'])} шт", border=0, align='C')
                
                pdf.set_xy(x + sum(col_widths[:4]), y_center)
                pdf.cell(col_widths[4], 6, txt=f"{row['Ціна']:.2f}", border=0, align='C')
                
                pdf.set_xy(x + sum(col_widths[:5]), y_center)
                pdf.cell(col_widths[5], 6, txt=f"{row['Сума']:.2f}", border=0, align='C')
                
                pdf.set_xy(x, y + row_height)
                total_invoice_sum += row['Сума']
            
            pdf.ln(5)
            
            pdf.set_font("Roboto", size=11, style='B')
            pdf.cell(0, 8, txt=f"Разом: {total_invoice_sum:.2f}", ln=True, align='R')
            pdf.ln(2)
            
            pdf.set_font("Roboto", size=10)
            pdf.cell(0, 6, txt=f"Всього найменувань {len(summary_df)}, на суму {total_invoice_sum:.2f} грн", ln=True, align='L')
            
            sum_words = number_to_words_uah(total_invoice_sum)
            pdf.set_font("Roboto", size=10, style='B')
            pdf.cell(0, 6, txt=sum_words, ln=True, align='L')
            pdf.ln(15)
            
            pdf.set_font("Roboto", size=10, style='B')
            x_sig = pdf.get_x()
            y_sig = pdf.get_y()
            pdf.cell(90, 10, txt="Від виконавця  ________________________", border=0, align='L')
            pdf.set_xy(x_sig + 90, y_sig)
            pdf.cell(100, 10, txt="Отримав(ла)  ________________________", border=0, align='R')
            
            pdf_bytes = bytes(pdf.output())
            
            st.success("✅ PDF-накладну успішно згенеровано!")
            st.download_button(
                label="Завантажити видаткову (PDF)",
                data=pdf_bytes,
                file_name=file_name_out,
                mime="application/pdf"
            )
        else:
            st.warning("Не вдалося розпізнати товари. Перевірте формат рахунків.")
            
            st.markdown("---")
            st.write("🛠 **Діагностика (для пошуку помилок)**")
            for filename, raw_text in debug_logs.items():
                if raw_text.strip():
                    with st.expander(f"Сирий текст з файлу {filename}"):
                        st.text(raw_text)
