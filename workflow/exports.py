from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def purchase_workbook(documents):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '구매요청서'
    sheet.append(['성명', '품명', '수량', '단가', '총가격', '신청사유'])
    for doc in documents:
        sheet.append([doc.owner.first_name, doc.product, doc.quantity,
                      doc.unit_price, doc.total_price, doc.reason])
        # User-entered text remains literal, even when it starts with '='.
        for column in [1, 2, 6]:
            sheet.cell(sheet.max_row, column).data_type = 's'
        for column in [4, 5]:
            sheet.cell(sheet.max_row, column).number_format = '#,##0'
        for cell in sheet[sheet.max_row]:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
    for cell in sheet[1]:
        cell.fill = PatternFill('solid', fgColor='315D43')
        cell.font = Font(color='FFFFFF', bold=True)
    for column, width in [('A', 16), ('B', 32), ('C', 10), ('D', 18), ('E', 20), ('F', 55)]:
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    return workbook


def leave_balances_workbook(rows, year):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f'{year}년 연차 현황'
    sheet.append(['연도', '성명', '부서', '직급', '총연차', '사용연차', '잔여연차'])
    for row in rows:
        person = row['user']
        sheet.append([year, person.first_name or person.username, person.profile.department,
                      person.profile.rank, row['total'], row['used'], row['remaining']])
        for column in [2, 3, 4]:
            sheet.cell(sheet.max_row, column).data_type = 's'
        for column in [5, 6, 7]:
            cell = sheet.cell(sheet.max_row, column)
            cell.number_format = '#,##0' if cell.value == int(cell.value) else '#,##0.##'
            if cell.value < 0:
                cell.font = Font(color='A13F31')
    for cell in sheet[1]:
        cell.fill = PatternFill('solid', fgColor='315D43')
        cell.font = Font(color='FFFFFF', bold=True)
    for column in 'ABCDEFG':
        sheet.column_dimensions[column].width = 18
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    return workbook
