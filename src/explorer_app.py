import os
import sqlite3
import pandas as pd
import streamlit as st
from jose import jwt, JWTError
import plotly.express as px

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(APP_DIR, ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "analysis", "resources", "Chinook.db")
DASHBOARD_DIR = os.path.join(PROJECT_ROOT, "analysis", "dashboards")
FAVICON_PATH = os.path.join(PROJECT_ROOT, "public", "favicon.png")

st.set_page_config(
    page_title="Smart Query - Analytics & Database Explorer",
    page_icon=FAVICON_PATH,
    layout="wide",
    initial_sidebar_state="collapsed"
)

def get_config(key: str, default: str | None = None) -> str | None:
    """Read a config value from Streamlit secrets, falling back to an
    environment variable. st.secrets raises if no secrets file exists at
    all (e.g. local dev), so that case is treated the same as a miss."""
    try:
        value = st.secrets.get(key)
    except Exception:
        value = None
    return value or os.getenv(key, default)

STREAMLIT_AUTH_SECRET = get_config("CHAINLIT_AUTH_SECRET")
MAIN_APP_URL = get_config("MAIN_APP_URL", "https://smartquery-22ix.onrender.com")

def get_sso_token():
    try:
        return st.query_params.get("sso_token")
    except Exception:
        return None

def authenticate_streamlit():
    token = get_sso_token()
    if not token or not STREAMLIT_AUTH_SECRET:
        return None

    try:
        payload = jwt.decode(token, STREAMLIT_AUTH_SECRET, algorithms=["HS256"])
        if payload.get("purpose") != "streamlit_sso":
            return None
        if not payload.get("sub") or not payload.get("email"):
            return None
        return {
            "id": payload["sub"],
            "email": payload["email"],
            "name": payload.get("name") or payload["email"],
        }
    except JWTError:
        return None

if "smartquery_auth_user" not in st.session_state:
    st.session_state.smartquery_auth_user = authenticate_streamlit()

AUTH_USER = st.session_state.smartquery_auth_user

if not AUTH_USER:
    st.title("🔐 Smart Query")
    st.warning("Please sign in through the Smart Query website to access Analytics & Explorer.")
    st.link_button("Sign in to Smart Query", MAIN_APP_URL.rstrip("/") + "/login?next=/explorer")
    st.stop()

# Remove the token from the browser URL after successful validation.
try:
    st.query_params.clear()
except Exception:
    pass

# Custom CSS: hide Streamlit chrome, reset layout, style metric cards + tabs.
with open(os.path.join(PROJECT_ROOT, "public", "css", "explorer_app.css")) as css:
    st.markdown(f"<style>{css.read()}</style>", unsafe_allow_html=True)


def get_db_connection():
    """Open the Chinook SQLite database using an absolute project path."""
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(
            f"Chinook database not found at: {DB_PATH}. "
            "Make sure analysis/resources/Chinook.db is included in the repository."
        )
    return sqlite3.connect(DB_PATH)

# Retrieve tables
def get_tables():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cursor.fetchall()]
    return sorted(tables)

def metric_card(label: str, value: str) -> None:
    """Render one KPI card using the .metric-card CSS class defined above."""
    st.markdown(f'<div class="metric-card"><h3>{label}</h3><p>{value}</p></div>', unsafe_allow_html=True)

st.title("📊 Smart Query - Analytics Suite & Data Explorer")

# Tabs for separate sections
tab_dashboard, tab_explorer = st.tabs([
    "📈 Interactive Analytics & Power BI Showcase",
    "🗄️ Database CSV Table Explorer"
])

# ----------------- TAB 1: INTERACTIVE DASHBOARD & SHOWCASE -----------------
with tab_dashboard:
    st.markdown("### 🔍 Live SQLite Analytics Dashboard")
    
    # Connection & Queries for dashboard
    with get_db_connection() as conn:
        # KPI Calculations
        kpi_revenue = pd.read_sql_query("SELECT SUM(Total) FROM Invoice;", conn).iloc[0, 0]
        kpi_orders = pd.read_sql_query("SELECT COUNT(InvoiceId) FROM Invoice;", conn).iloc[0, 0]
        kpi_customers = pd.read_sql_query("SELECT COUNT(CustomerId) FROM Customer;", conn).iloc[0, 0]
        kpi_countries = pd.read_sql_query("SELECT COUNT(DISTINCT BillingCountry) FROM Invoice;", conn).iloc[0, 0]

        # Visual charts data
        genre_query = """
            SELECT g.Name as Genre, SUM(il.UnitPrice * il.Quantity) as Sales
            FROM InvoiceLine il
            JOIN Track t ON il.TrackId = t.TrackId
            JOIN Genre g ON t.GenreId = g.GenreId
            GROUP BY Genre
            ORDER BY Sales DESC
            LIMIT 10;
        """
        df_genre = pd.read_sql_query(genre_query, conn)

        trend_query = """
            SELECT strftime('%Y-%m', InvoiceDate) as Month, SUM(Total) as Revenue
            FROM Invoice
            GROUP BY Month
            ORDER BY Month ASC;
        """
        df_trend = pd.read_sql_query(trend_query, conn)

        country_query = """
            SELECT BillingCountry as Country, SUM(Total) as Revenue
            FROM Invoice
            GROUP BY Country
            ORDER BY Revenue DESC;
        """
        df_country = pd.read_sql_query(country_query, conn)

        customer_query = """
            SELECT c.FirstName || ' ' || c.LastName as Customer, SUM(i.Total) as Spend
            FROM Customer c
            JOIN Invoice i ON c.CustomerId = i.CustomerId
            GROUP BY Customer
            ORDER BY Spend DESC
            LIMIT 10;
        """
        df_customer = pd.read_sql_query(customer_query, conn)

    # 4 columns for KPI display
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("💰 Total Store Revenue", f"${kpi_revenue:,.2f}")
    with col2:
        metric_card("🛒 Total Orders Placed", str(kpi_orders))
    with col3:
        metric_card("👤 Active Customers", str(kpi_customers))
    with col4:
        metric_card("🌍 Countries Served", str(kpi_countries))
        
    st.write("")
    st.write("")

    # Visual charts layout
    col_left, col_right = st.columns(2)
    
    with col_left:
        fig_genre = px.bar(
            df_genre, x="Sales", y="Genre", orientation="h",
            title="🎸 Sales Revenue by Music Genre (Top 10)",
            labels={"Sales": "Revenue ($)", "Genre": "Music Genre"},
            template="plotly_dark",
            color="Sales",
            color_continuous_scale="Viridis",
            height=450
        )
        fig_genre.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            margin=dict(t=60, b=50, l=160, r=40)
        )
        st.plotly_chart(fig_genre, use_container_width=True)
        
        fig_trend = px.line(
            df_trend, x="Month", y="Revenue",
            title="📈 Monthly Store Revenue Trends",
            labels={"Revenue": "Revenue ($)", "Month": "Billing Month"},
            template="plotly_dark"
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    with col_right:
        fig_country = px.choropleth(
            df_country, locations="Country", locationmode="country names",
            color="Revenue", hover_name="Country",
            title="🌍 Global Revenue Distribution Map",
            color_continuous_scale="Plasma",
            template="plotly_dark"
        )
        st.plotly_chart(fig_country, use_container_width=True)

        fig_customer = px.bar(
            df_customer, x="Customer", y="Spend",
            title="👑 Top 10 High-Spending Customers",
            labels={"Spend": "Total Spend ($)", "Customer": "Customer Name"},
            template="plotly_dark",
            color="Spend",
            color_continuous_scale="Magenta"
        )
        st.plotly_chart(fig_customer, use_container_width=True)

    st.markdown("---")
    st.markdown("### 📊 Power BI Dashboard Portfolio Showcase")
    st.markdown("Below are interactive visual pages designed using Power BI Desktop. Since personal accounts are blocked from publishing online, you can inspect each dashboard preview page and download the complete `.pbix` desktop package below.")

    # PBIX Download Button
    pbix_path = os.path.join(DASHBOARD_DIR, "Chinook Dashboard.pbix")
    if os.path.exists(pbix_path):
        with open(pbix_path, "rb") as f:
            pbix_bytes = f.read()
        st.download_button(
            label="📥 Download Power BI File (.pbix Package)",
            data=pbix_bytes,
            file_name="Chinook Dashboard.pbix",
            mime="application/octet-stream",
            help="Click here to download the full interactive Power BI report to open in Power BI Desktop.",
            on_click="ignore"
        )
    else:
        st.warning("Power BI file 'Chinook Dashboard.pbix' not found.")

    st.write("")

    # Visual showcases in 2x2 grid
    grid_col1, grid_col2 = st.columns(2)
    with grid_col1:
        st.subheader("🏠 Page 1: Overview Dashboard")
        st.image(os.path.join(DASHBOARD_DIR, "Overview.png"), caption="Headline KPIs, Customer Totals, and Billing Distribution Map", use_container_width=True)
        st.subheader("🙋 Page 2: Customer Insights")
        st.image(os.path.join(DASHBOARD_DIR, "Customer insights.png"), caption="Top Customer spend dynamics, Average Purchase value, and Yearly trends", use_container_width=True)
        
    with grid_col2:
        st.subheader("💰 Page 3: Sales Analysis")
        st.image(os.path.join(DASHBOARD_DIR, "Sales analysis.png"), caption="Genre sales breakdown, Employee sales quotas, and Monthly revenue cycles", use_container_width=True)
        st.subheader("🌍 Page 4: Country Analysis")
        st.image(os.path.join(DASHBOARD_DIR, "Country analysis.png"), caption="Country-by-country sales performance metrics and Genre country splits", use_container_width=True)


# ----------------- TAB 2: DATABASE CSV TABLE EXPLORER -----------------
with tab_explorer:
    st.markdown("### 🗄️ Chinook Relational Database Explorer (Read-Only)")
    st.markdown("Browse, filter, and export any table from the Chinook relational database as a CSV format.")

    tables = get_tables()
    selected_table = st.selectbox("📋 Select Database Table to Inspect:", tables)

    if selected_table:
        with get_db_connection() as conn:
            # Load table info & data
            df = pd.read_sql_query(f"SELECT * FROM {selected_table};", conn)

            # Display schema column details
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({selected_table});")
            columns_info = cursor.fetchall()

        # Display table statistics
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.metric(label="📊 Total Rows in Table", value=len(df))
        with col_t2:
            st.metric(label="🧬 Number of Columns", value=len(df.columns))

        st.markdown("#### 🔍 Schema Structure Details")
        cols_df = pd.DataFrame(columns_info, columns=["CID", "Column Name", "Type", "Not Null", "Default Value", "Primary Key"])
        st.dataframe(cols_df, use_container_width=True, hide_index=True)

        st.markdown(f"#### 📋 Table Data View - {selected_table}")
        
        # Simple Search box to filter data interactively
        search_term = st.text_input("🔍 Search rows in table (matches any text cell):", "")
        if search_term:
            filtered_df = df[df.astype(str).apply(lambda row: row.str.contains(search_term, case=False, regex=False).any(), axis=1)]
        else:
            filtered_df = df

        st.dataframe(filtered_df, use_container_width=True)

        # Download Table CSV Button
        csv_data = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label=f"📥 Export {selected_table} Table to CSV",
            data=csv_data,
            file_name=f"Chinook_{selected_table}.csv",
            mime="text/csv",
            on_click="ignore"
        )

        st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)