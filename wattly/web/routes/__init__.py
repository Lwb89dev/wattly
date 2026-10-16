"""Blueprint registration."""

from wattly.web.routes import analytics, bills, compare, dashboard, exporting, importer, settings


def register_blueprints(app) -> None:
    for module in (dashboard, bills, importer, analytics, compare, settings, exporting):
        app.register_blueprint(module.bp)
