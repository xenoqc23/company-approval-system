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
