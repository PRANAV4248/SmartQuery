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

try:
    STREAMLIT_AUTH_SECRET = st.secrets.get("CHAINLIT_AUTH_SECRET")
except Exception:
    STREAMLIT_AUTH_SECRET = None
if not STREAMLIT_AUTH_SECRET:
    STREAMLIT_AUTH_SECRET = os.getenv("CHAINLIT_AUTH_SECRET")

try:
    MAIN_APP_URL = st.secrets.get("MAIN_APP_URL")
except Exception:
    MAIN_APP_URL = None
if not MAIN_APP_URL:
    MAIN_APP_URL = os.getenv("MAIN_APP_URL", "https://smartquery-22ix.onrender.com")


def _get_sso_token():
    try:
        return st.query_params.get("sso_token")
    except Exception:
        return None


def _authenticate_streamlit():
    token = _get_sso_token()
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
    st.session_state.smartquery_auth_user = _authenticate_streamlit()

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


# Sidebar intentionally hidden; authentication is handled by SmartQuery SSO.


# Hide Streamlit's built-in sidebar, footer, and chrome.
st.markdown("""
<style>
    /* Completely hide Streamlit's sidebar */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"],
    [data-testid="stSidebarNav"] {
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
    }

    /* Hide "Built with Streamlit" footer and fullscreen controls */
    footer,
    [data-testid="stFooter"],
    #MainMenu {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
    }

    /* Hide Streamlit top chrome */
    header[data-testid="stHeader"],
    [data-testid="stDecoration"],
    #stDecoration,
    [data-testid="stToolbar"],
    .stToolbar,
    .stAppDeployButton,
    button[kind="header"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
    }

    /* Use the complete embedded width */
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .main {
        margin-left: 0 !important;
        padding-left: 0 !important;
    }

    .main .block-container,
    [data-testid="stAppViewContainer"] > section:first-child,
    section.main > div:first-child {
        max-width: none !important;
        width: 100% !important;
        padding-top: 0 !important;
        padding-bottom: 120px !important;
        margin-top: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# Hide Streamlit's built-in navbar/toolbar (Deploy button, hamburger menu, header bar)
st.markdown("""
<style>
    /* Streamlit top toolbar / header bar */
    header[data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    #stDecoration,
    .stToolbar,
    .stAppDeployButton,
    button[kind="header"],
    [data-testid="stAppViewBlockContainer"] > div:first-child > div:first-child > div:first-child > div:first-child[style*="height: 2.875rem"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        overflow: hidden !important;
    }
    /* Kill the flex/grid GAP Streamlit reserves between the (hidden) header
       and the main content — collapsing the header's height alone doesn't
       remove this, since the gap is a property of the parent flex container. */
    [data-testid="stAppViewContainer"],
    [data-testid="stApp"],
    .stApp,
    [data-testid="stMain"] {
        gap: 0 !important;
        row-gap: 0 !important;
    }

    /* Remove ALL top padding/margin Streamlit reserves for the hidden header */
    .main .block-container,
    [data-testid="stAppViewContainer"] > section:first-child,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    section.main > div:first-child,
    .stMainBlockContainer,
    div[data-testid="stAppViewBlockContainer"],
    div[data-testid="stVerticalBlock"],
    div[data-testid="stVerticalBlockBorderWrapper"]:first-of-type {
        padding-top: 0rem !important;
        margin-top: 0rem !important;
    }

    /* Extra bottom breathing room so the final dashboard charts
       are never hidden by the embedded viewport/footer area. */
    .main .block-container,
    [data-testid="stAppViewContainer"] .block-container,
    div[data-testid="stAppViewBlockContainer"],
    .stMainBlockContainer {
        padding-top: 1rem !important;
        padding-bottom: 120px !important;
    }

    /* Reduce the large gap between the SmartQuery navbar and the dashboard title */
    .main .block-container h1:first-of-type,
    div[data-testid="stAppViewBlockContainer"] h1:first-of-type {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# Dark theme custom css injection for consistent dark styling
st.markdown("""
<style>
    .reportview-container {
        background: #0f1115;
    }
    .metric-card {
        background-color: #171c24;
        border: 1px solid #232c3d;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2);
    }
    .metric-card h3 {
        margin: 0;
        color: #8c9ba5;
        font-size: 14px;
        font-weight: 500;
    }
    .metric-card p {
        margin: 5px 0 0 0;
        color: #ffffff;
        font-size: 24px;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# Tab styling — full-width two-column layout, centered, larger text
st.markdown("""
<style>
    /* Full-width flex tab row */
    [data-testid="stTabs"] > div:first-child [role="tablist"] {
        display: flex !important;
        width: 100% !important;
        gap: 0 !important;
        border-bottom: 1px solid rgba(255,255,255,0.1) !important;
    }

    /* Each tab: equal 50% width, centered, large */
    [data-testid="stTabs"] > div:first-child [role="tab"] {
        flex: 1 1 50% !important;
        justify-content: center !important;
        text-align: center !important;
        font-size: 2.5rem !important;
        font-weight: 600 !important;
        padding: 1rem 1rem !important;
        letter-spacing: 0.01em !important;
        border-radius: 0 !important;
        transition: color 0.2s, background 0.2s !important;
    }

    /* Active tab — WHITE text, BLUE underline */
    [data-testid="stTabs"] > div:first-child [role="tab"][aria-selected="true"] {
        color: #ffffff !important;
        border-bottom: 3px solid #0882ff !important;
        background: transparent !important;
    }

    /* Inactive tab — muted grey, no underline */
    [data-testid="stTabs"] > div:first-child [role="tab"][aria-selected="false"] {
        color: #888888 !important;
        border-bottom: 3px solid transparent !important;
    }

    /* Hover state */
    [data-testid="stTabs"] > div:first-child [role="tab"]:hover {
        color: #dddddd !important;
        background: rgba(255,255,255,0.04) !important;
    }

    /* Remove Streamlit's default red active tab line */
    [data-testid="stTabs"] > div:first-child [role="tab"][aria-selected="true"]::before,
    [data-testid="stTabs"] > div:first-child [role="tab"][aria-selected="true"]::after,
    [data-testid="stTabsDivider"],
    [data-baseweb="tab-highlight"] {
        display: none !important;
        background: transparent !important;
        border: none !important;
    }
</style>
""", unsafe_allow_html=True)




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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return sorted(tables)

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
    conn = get_db_connection()
    
    # KPI Calculations
    kpi_revenue = pd.read_sql_query("SELECT SUM(Total) FROM Invoice;", conn).iloc[0, 0]
    kpi_orders = pd.read_sql_query("SELECT COUNT(InvoiceId) FROM Invoice;", conn).iloc[0, 0]
    kpi_customers = pd.read_sql_query("SELECT COUNT(CustomerId) FROM Customer;", conn).iloc[0, 0]
    kpi_countries = pd.read_sql_query("SELECT COUNT(DISTINCT BillingCountry) FROM Invoice;", conn).iloc[0, 0]
    
    # 4 columns for KPI display
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="metric-card"><h3>💰 Total Store Revenue</h3><p>${kpi_revenue:,.2f}</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><h3>🛒 Total Orders Placed</h3><p>{kpi_orders}</p></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><h3>👤 Active Customers</h3><p>{kpi_customers}</p></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><h3>🌍 Countries Served</h3><p>{kpi_countries}</p></div>', unsafe_allow_html=True)
        
    st.write("")
    st.write("")

    # Visual charts layout
    col_left, col_right = st.columns(2)
    
    with col_left:
        # Genre sales breakdown
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
        
        # Monthly Revenue trends
        trend_query = """
            SELECT strftime('%Y-%m', InvoiceDate) as Month, SUM(Total) as Revenue
            FROM Invoice
            GROUP BY Month
            ORDER BY Month ASC;
        """
        df_trend = pd.read_sql_query(trend_query, conn)
        fig_trend = px.line(
            df_trend, x="Month", y="Revenue",
            title="📈 Monthly Store Revenue Trends",
            labels={"Revenue": "Revenue ($)", "Month": "Billing Month"},
            template="plotly_dark"
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    with col_right:
        # Country sales breakdown
        country_query = """
            SELECT BillingCountry as Country, SUM(Total) as Revenue
            FROM Invoice
            GROUP BY Country
            ORDER BY Revenue DESC;
        """
        df_country = pd.read_sql_query(country_query, conn)
        fig_country = px.choropleth(
            df_country, locations="Country", locationmode="country names",
            color="Revenue", hover_name="Country",
            title="🌍 Global Revenue Distribution Map",
            color_continuous_scale="Plasma",
            template="plotly_dark"
        )
        st.plotly_chart(fig_country, use_container_width=True)

        # Top Customers
        customer_query = """
            SELECT c.FirstName || ' ' || c.LastName as Customer, SUM(i.Total) as Spend
            FROM Customer c
            JOIN Invoice i ON c.CustomerId = i.CustomerId
            GROUP BY Customer
            ORDER BY Spend DESC
            LIMIT 10;
        """
        df_customer = pd.read_sql_query(customer_query, conn)
        fig_customer = px.bar(
            df_customer, x="Customer", y="Spend",
            title="👑 Top 10 High-Spending Customers",
            labels={"Spend": "Total Spend ($)", "Customer": "Customer Name"},
            template="plotly_dark",
            color="Spend",
            color_continuous_scale="Magenta"
        )
        st.plotly_chart(fig_customer, use_container_width=True)

    conn.close()

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
        conn = get_db_connection()
        
        # Load table info & data
        df = pd.read_sql_query(f"SELECT * FROM {selected_table};", conn)
        
        # Display schema column details
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({selected_table});")
        columns_info = cursor.fetchall()
        
        conn.close()

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
            filtered_df = df[df.astype(str).apply(lambda row: row.str.contains(search_term, case=False).any(), axis=1)]
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