from htmltools._core import Tag
from shiny import App, ui, reactive, render
from shinywidgets import output_widget, render_widget  

import polars as pl
import io

from data import get_data, fetch_raw_data
from i18n import i18n
import plotly.express as px

df = get_data()


def apply_plot_interaction_defaults(fig):
   fig.update_layout(dragmode="pan")
   fig.update_layout(modebar_remove=['select2d', 'lasso2d'])
   return fig

# compile ui
app_ui = ui.page_fluid(
   ui.row(
      ui.tags.div(
         {"class": "col-12 col-xl-6"},
         output_widget("time_plot"),
      ),
      ui.tags.div(
         {"class": "col-12 col-xl-6"},
         output_widget("category_plot"),
      ),
   )
)


def server(input, output, session):
   @render_widget # pyrefly: ignore
   def time_plot():
      freq = (
         df.group_by("Announcement_Year")
         .agg(pl.count().alias("frequency"))
         .sort("Announcement_Year")
      )
      fig = px.bar(
         freq,
         x="Announcement_Year",
         y="frequency",
         title=i18n("气候目标年度发布数量"),
         color_discrete_sequence=["#385E4B"]
      )
      fig.update_xaxes(title_text=i18n("发布年份"), tickangle=-45)
      fig.update_yaxes(title_text=i18n("数量"))
      fig.update_layout(yaxis_fixedrange=True)
      fig.update_layout(
         xaxis_tickangle=-45,
         plot_bgcolor="white",
         paper_bgcolor="white"
      )
      return apply_plot_interaction_defaults(fig)
   @render_widget # pyrefly: ignore
   def category_plot():
      category_freq = (
         df.group_by("Target_Category")
         .agg(pl.count().alias("frequency"))
         .sort("frequency")
      )
      fig = px.bar(
         category_freq,
         x="frequency",
         y="Target_Category",
         title=i18n("气候目标类型发布数量"),
         color_discrete_sequence=["#385E4B"]
      )
      fig.update_xaxes(title_text=i18n("气候目标类型"))
      fig.update_yaxes(title_text=i18n("数量"))
      fig.update_layout(
         plot_bgcolor="white",
         paper_bgcolor="white"
      )
      return apply_plot_interaction_defaults(fig)

app = App(app_ui, server, debug=False)
