import xml.etree.ElementTree as ET


def decode_uploaded_xml(content: bytes) -> tuple[str, str]:
    try:
        return content.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return content.decode("latin-1"), "latin-1"


def parse_xml_safely(xml_text: str) -> tuple[bool, str]:
    try:
        ET.fromstring(xml_text)
        return True, ""
    except ET.ParseError:
        return False, (
            "Le fichier XML semble mal forme (balise non fermee ou structure invalide). "
            "Corrigez le fichier puis reessayez."
        )
