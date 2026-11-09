import unittest
from xml.etree.ElementTree import fromstring
from toast_content import reminder_xml


class ReminderContentTests(unittest.TestCase):
    def test_reminder_has_an_explicit_system_dismiss_button_and_silent_audio(self):
        content=fromstring(reminder_xml('미결 2건','홍길동 · 휴가원','확인은 알림만 닫습니다.'))
        self.assertEqual(content.attrib,{'scenario':'reminder'})
        action=content.find('actions/action')
        self.assertEqual(action.attrib,{'content':'확인','arguments':'dismiss','activationType':'system'})
        self.assertEqual(content.find('audio').get('silent'),'true')
        self.assertIsNone(content.get('launch'))

    def test_unicode_and_xml_special_characters_remain_text(self):
        values=['제목 <기안>','홍길동 & "구매"\n</text><actions>','확인 → 닫기']
        root=fromstring(reminder_xml(*values))
        self.assertEqual([n.text for n in root.findall('visual/binding/text')],values)
        self.assertEqual(len(root.findall('actions')),1)


if __name__=='__main__':unittest.main()
