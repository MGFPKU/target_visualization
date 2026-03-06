from htmltools._core import Tag
from shiny import App, ui, reactive, render

import polars as pl
import io

from data import get_data, fetch_raw_data
from i18n import i18n

df = get_data()

# compile ui
app_ui = ui.page_fluid(
)


def server(input, output, session):
   pass


app = App(app_ui, server, debug=False)
