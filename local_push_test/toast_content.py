"""Native reminder content; acknowledgement dismisses only the notification."""
from xml.etree.ElementTree import Element,SubElement,tostring


def reminder_xml(title,body,footer):
    toast=Element('toast',scenario='reminder')
    binding=SubElement(SubElement(toast,'visual'),'binding',template='ToastGeneric')
    for value in [title,body,footer]:SubElement(binding,'text').text=value
    actions=SubElement(toast,'actions')
    SubElement(actions,'action',content='확인',arguments='dismiss',activationType='system')
    SubElement(toast,'audio',silent='true')
    return tostring(toast,encoding='unicode')
