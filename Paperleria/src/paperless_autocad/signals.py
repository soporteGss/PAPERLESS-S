def get_parser(*args, **kwargs):
    from paperless_autocad.parsers import AutocadDocumentParser

    return AutocadDocumentParser(*args, **kwargs)


def autocad_consumer_declaration(sender, **kwargs):
    return {
        "parser": get_parser,
        "weight": 10,
        "mime_types": {
            "image/vnd.dwg": ".dwg",
            "application/acad": ".dwg",
            "image/x-dwg": ".dwg",
            "application/x-dwg": ".dwg",
            "image/vnd.dxf": ".dxf",
            "application/dxf": ".dxf",
        },
    }
