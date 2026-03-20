from django.apps import AppConfig

from paperless_autocad.signals import autocad_consumer_declaration


class PaperlessAutocadConfig(AppConfig):
    name = "paperless_autocad"

    def ready(self) -> None:
        from documents.signals import document_consumer_declaration

        document_consumer_declaration.connect(autocad_consumer_declaration)
        AppConfig.ready(self)
