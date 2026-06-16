"""
Seed Knowledge - Pre-populated knowledge entries.

Contains:
1. Tool usage issues and solutions (Data Engine, etc.)
2. Database patterns and common errors
3. Backend API patterns
4. Frontend UI/UX patterns and React issues
5. Docker/deployment patterns
6. Integration issues

Call seed_knowledge() to populate a fresh knowledge store.
"""

from .types import Knowledge, KnowledgeCategory, Severity
from .store import KnowledgeStore


def get_seed_knowledge() -> list:
    """Get all seed knowledge entries"""
    return [
        # =====================================================================
        # TOOL USAGE - Data Engine (CRITICAL)
        # =====================================================================
        Knowledge(
            title="generate_seed_sql requires field_mapping parameter",
            category=KnowledgeCategory.TOOL_USAGE,
            severity=Severity.CRITICAL,
            summary="The generate_seed_sql tool MUST be called with field_mapping to map dataset columns to your database schema.",
            problem="Calling generate_seed_sql without field_mapping causes the tool to fail with 'missing required argument'.",
            symptoms=[
                "generate_seed_sql FAILED: missing required argument 'field_mapping'",
                "execute() missing 1 required positional argument: 'field_mapping'",
                "TypeError: generate_seed_sql()"
            ],
            root_cause="The tool requires explicit mapping from HuggingFace dataset columns to your database table columns.",
            solution="""Always provide field_mapping when calling generate_seed_sql:
1. First use preview_dataset to see available columns
2. Create a mapping from dataset columns to your table columns
3. Include ALL required columns in the mapping""",
            example_code="""generate_seed_sql(
    dataset_id="FronkonGames/steam-games-dataset",
    table_name="games",
    field_mapping={
        "AppID": "steam_app_id",
        "Name": "title",
        "About the game": "about",
        "Header image": "header_image_url",
        "Price": "price_cents"
    },
    output_file="app/database/init/03_real_data.sql",
    limit=200
)""",
            wrong_code="""generate_seed_sql(
    dataset_id="FronkonGames/steam-games-dataset",
    table_name="games",
    output_file="app/database/init/03_real_data.sql"
)  # WRONG: Missing field_mapping!""",
            tags=["data-engine", "huggingface", "database", "seed-data", "generate_seed_sql", "critical"],
            applies_to=["database"]
        ),
        
        Knowledge(
            title="Always use generate_seed_sql after preview_dataset",
            category=KnowledgeCategory.TOOL_USAGE,
            severity=Severity.CRITICAL,
            summary="If you preview a dataset, you MUST use generate_seed_sql to create the seed data - do NOT manually write SQL.",
            problem="Agents sometimes preview a dataset to understand its structure but then manually write INSERT statements instead of using the data engine.",
            symptoms=[
                "Manually written INSERT statements with placeholder data",
                "Seed data doesn't match the previewed dataset",
                "Fabricated data in seed files after preview"
            ],
            root_cause="The agent understands the dataset structure but forgets to use the tool to generate actual data.",
            solution="""Workflow MUST be:
1. discover_datasets() - find relevant datasets
2. preview_dataset() - understand structure and columns
3. generate_seed_sql() - generate actual INSERT statements
4. NEVER manually write seed data after previewing!

SELF-CHECK: If you called preview_dataset(), did you also call generate_seed_sql()?
- If NO → GO BACK AND CALL generate_seed_sql() NOW!""",
            tags=["data-engine", "workflow", "seed-data", "preview_dataset"],
            applies_to=["database"]
        ),
        
        Knowledge(
            title="Use flexible search terms for HuggingFace dataset discovery",
            category=KnowledgeCategory.DATA_MAPPING,
            severity=Severity.HIGH,
            summary="When searching for datasets, use generic terms rather than brand names.",
            problem="Searching for exact brand names often returns no results because datasets rarely use trademarked names.",
            symptoms=[
                "discover_datasets returns empty results",
                "No datasets found for search term"
            ],
            solution="""Use generic, descriptive terms:
- Instead of 'airbnb' → 'housing listings', 'vacation rentals', 'property rentals'
- Instead of 'uber' → 'ride sharing', 'taxi trips', 'transportation'
- Instead of 'doordash' → 'food delivery', 'restaurant orders'

Known working datasets:
- Steam games: FronkonGames/steam-games-dataset
- Movies: imdb, movies, Pablinho/movies-dataset
- Housing: davidberenstein1957/insideairbnb-listings-paris-2024
- Music: maharshipandya/spotify-tracks-dataset
- Products: Amazon products, e-commerce""",
            tags=["data-engine", "huggingface", "dataset-search"],
            applies_to=["design", "database"]
        ),

        Knowledge(
            title="Never generate fake external IDs with generate_series",
            category=KnowledgeCategory.SEED_DATA,
            severity=Severity.CRITICAL,
            summary="Never use generate_series to fabricate IDs for external services (Steam CDN, Amazon, etc.)",
            problem="Using generate_series() to create fake IDs for external services results in 404 errors for all generated URLs.",
            symptoms=[
                "All images show 404 broken",
                "Steam CDN URLs return 404",
                "Hundreds of broken image links"
            ],
            root_cause="External CDN URLs only work for REAL IDs. Fabricated IDs like 100001-100210 don't exist on Steam.",
            solution="""NEVER fabricate external IDs!

Option 1: Use generate_seed_sql() with REAL data from HuggingFace
Option 2: Use search_photos() for supplemental images
Option 3: Use picsum.photos with internal seeds (not external IDs)
Option 4: Use placehold.co for explicit placeholders""",
            wrong_code="""-- NEVER DO THIS! Fake IDs don't exist!
SELECT
  'https://cdn.cloudflare.steamstatic.com/steam/apps/' || (100000 + i) || '/header.jpg'
FROM generate_series(1, 210);
-- Result: 210 broken images!""",
            example_code="""-- Use generate_seed_sql with real data instead!
generate_seed_sql(
    dataset_id="FronkonGames/steam-games-dataset",
    table_name="games",
    field_mapping={"AppID": "steam_app_id", "Header image": "header_image_url"},
    filters={"Header image": {"not_empty": True}},
    output_file="app/database/init/02_seed.sql",
    limit=200
)""",
            tags=["database", "seed-data", "images", "external-urls", "critical"],
            applies_to=["database"]
        ),

        # =====================================================================
        # DATABASE PATTERNS
        # =====================================================================
        Knowledge(
            title="PostgreSQL version lock-in with Docker volumes",
            category=KnowledgeCategory.DB_SCHEMA,
            severity=Severity.HIGH,
            summary="Changing PostgreSQL version causes 'database files incompatible' error.",
            problem="Once PostgreSQL creates data files with a specific version, changing versions in Dockerfile breaks the database.",
            solution="""Always specify explicit version in Dockerfile and NEVER change it:
FROM postgres:16-alpine

If you must change versions, users need to delete volumes: docker compose down -v""",
            tags=["database", "postgresql", "docker", "volumes"],
            applies_to=["database"]
        ),

        Knowledge(
            title="SQL init script execution order",
            category=KnowledgeCategory.DB_SCHEMA,
            severity=Severity.HIGH,
            summary="Use numbered prefixes for init script execution order.",
            problem="Foreign key constraints fail because tables created out of order.",
            solution="""Use numbered prefixes:
app/database/init/
├── 01_schema.sql    # Tables with dependencies first
├── 02_seed.sql      # Test data after all tables exist
└── 03_functions.sql # Optional: stored procedures

SQL files execute in alphabetical order, so 01_ runs before 02_.""",
            tags=["database", "postgresql", "init-scripts"],
            applies_to=["database"]
        ),

        Knowledge(
            title="Store prices in cents as INTEGER",
            category=KnowledgeCategory.DB_SCHEMA,
            severity=Severity.MEDIUM,
            summary="Always store prices in cents to avoid floating point errors.",
            problem="Floating point errors with decimal prices cause rounding issues.",
            solution="""ALWAYS store prices in cents as INTEGER:
price_cents INTEGER NOT NULL  -- $19.99 stored as 1999

Frontend converts: displayPrice = price_cents / 100""",
            tags=["database", "money", "prices"],
            applies_to=["database", "backend", "frontend"]
        ),

        Knowledge(
            title="Use ON CONFLICT for idempotent seed data",
            category=KnowledgeCategory.DB_SCHEMA,
            severity=Severity.MEDIUM,
            summary="Seed SQL should use ON CONFLICT (upsert) to allow re-running without errors.",
            problem="Running seed SQL twice causes duplicate key errors.",
            solution="""Use PostgreSQL ON CONFLICT clause:

INSERT INTO users (id, email, name) VALUES (...)
ON CONFLICT (email) DO UPDATE SET
    name = EXCLUDED.name,
    updated_at = NOW();

This makes seed files idempotent - safe to run multiple times.""",
            tags=["database", "postgresql", "seed-data", "upsert"],
            applies_to=["database"]
        ),

        Knowledge(
            title="Seed data must include items matching all filter options",
            category=KnowledgeCategory.SEED_DATA,
            severity=Severity.HIGH,
            summary="Include items that match every possible filter to ensure filters are testable.",
            problem="Filters like 'Free items' or 'On Sale' return 0 results because no seed data matches.",
            solution="""After main seed INSERT, add special items:

-- Set ~10% as FREE
UPDATE games SET is_free = true, price_cents = 0
WHERE id IN (SELECT id FROM games ORDER BY RANDOM() LIMIT (SELECT COUNT(*)/10 FROM games));

-- Add discounts to ~15% of PAID items
UPDATE games SET discount_percent = 25, discount_ends_at = NOW() + INTERVAL '7 days'
WHERE id IN (SELECT id FROM games WHERE is_free = false ORDER BY RANDOM() LIMIT ...);

-- Mark some as featured
UPDATE games SET is_featured = true
WHERE id IN (SELECT id FROM games ORDER BY popularity_score DESC LIMIT 12);""",
            tags=["database", "seed-data", "testing", "filters"],
            applies_to=["database"]
        ),

        Knowledge(
            title="generate_seed_sql only generates main table - must create junction tables",
            category=KnowledgeCategory.TOOL_USAGE,
            severity=Severity.HIGH,
            summary="generate_seed_sql() only generates INSERT for ONE table, NOT junction/association tables.",
            problem="Genre filter returns empty because games exist but have NO genre associations.",
            symptoms=[
                "Filter returns 0 results",
                "Junction table is empty",
                "Categories/genres not linked to items"
            ],
            solution="""After generate_seed_sql() for main table, create junction table data:

-- Create file: 04_associations.sql
-- Associate each game with 1-3 random genres
INSERT INTO game_genres (game_id, genre_id)
SELECT g.id, (SELECT id FROM genres ORDER BY RANDOM() LIMIT 1)
FROM games g
WHERE NOT EXISTS (SELECT 1 FROM game_genres gg WHERE gg.game_id = g.id)
ON CONFLICT DO NOTHING;""",
            tags=["database", "seed-data", "junction-tables", "associations"],
            applies_to=["database"]
        ),

        # =====================================================================
        # INTEGRATION ISSUES
        # =====================================================================
        Knowledge(
            title="Frontend API baseURL must match nginx proxy configuration",
            category=KnowledgeCategory.INTEGRATION,
            severity=Severity.CRITICAL,
            summary="http.js baseURL must include '/api' prefix to match nginx proxy routing.",
            problem="API requests return HTML instead of JSON because nginx routes non-/api requests to frontend.",
            symptoms=[
                "API response is HTML instead of JSON",
                "SyntaxError: Unexpected token '<'",
                "JSON.parse error on API response",
                "Getting index.html from API calls"
            ],
            root_cause="Frontend http.js has baseURL: '' but nginx only proxies /api/* to backend.",
            solution="""Set baseURL to '/api' in frontend http client:

// http.js
const http = axios.create({
    baseURL: '/api',  // MUST include /api
    timeout: 15000
});

This ensures /genres becomes /api/genres which nginx proxies to backend.""",
            example_code="""// Correct http.js
import axios from 'axios';

const http = axios.create({
    baseURL: '/api',
    timeout: 15000
});

export default http;""",
            wrong_code="""// Wrong - missing /api prefix
const http = axios.create({
    baseURL: '',  // This breaks nginx routing!
});""",
            tags=["frontend", "backend", "nginx", "api", "axios", "critical"],
            applies_to=["frontend", "backend"]
        ),

        Knowledge(
            title="Backend API must implement all filter parameters",
            category=KnowledgeCategory.API_PATTERN,
            severity=Severity.HIGH,
            summary="List endpoints must handle all common filter parameters.",
            problem="Filter UI elements exist but filters don't work because backend ignores query parameters.",
            symptoms=[
                "Filter selection has no effect",
                "Search returns all items regardless of query",
                "Pagination doesn't work"
            ],
            solution="""Backend routes must parse and apply ALL filter parameters:

const { q, page, limit, sort, genre, priceMin, priceMax, isFree, onSale } = req.query;

let where = ['is_active = true'];
const params = [];
let i = 1;

if (q) {
    where.push(`(title ILIKE $${i} OR description ILIKE $${i})`);
    params.push(`%${q}%`);
    i++;
}

if (isFree === 'true') {
    where.push('is_free = true');
}

if (onSale === 'true') {
    where.push('discount_percent > 0');
}

// Handle ALL other filters similarly...""",
            tags=["backend", "api", "filters", "search", "express"],
            applies_to=["backend"]
        ),

        Knowledge(
            title="API response wrapper must be consistent",
            category=KnowledgeCategory.API_PATTERN,
            severity=Severity.HIGH,
            summary="Use consistent response format across ALL endpoints.",
            problem="Frontend shows empty because different endpoints use different wrapper formats.",
            symptoms=[
                "UI shows empty but backend has data",
                "Cannot read property 'map' of undefined"
            ],
            solution="""Use consistent wrapper for ALL responses:

// List response - ALWAYS use data.items
res.json({
    success: true,
    data: {
        items: results,
        pagination: { total, limit, offset }
    }
});

// Single item response
res.json({
    success: true,
    data: item  // Direct object, not wrapped
});

// Error response
res.status(404).json({
    success: false,
    error: { code: 'NOT_FOUND', message: 'Not found' }
});""",
            tags=["backend", "api", "response-format"],
            applies_to=["backend", "frontend"]
        ),

        # =====================================================================
        # FRONTEND - React Patterns
        # =====================================================================
        Knowledge(
            title="JSX prop syntax for arrays and objects",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.HIGH,
            summary="Always wrap arrays and objects in curly braces in JSX props.",
            problem="Using prop=[...] instead of prop={[...]} causes syntax errors.",
            example_code="""// CORRECT
<Tabs tabs={['home', 'flights']} />
<Component config={{ key: 'value' }} />""",
            wrong_code="""// WRONG - Will cause syntax error!
<Tabs tabs=['home', 'flights'] />""",
            tags=["react", "jsx", "syntax"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Export both named and default exports",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.MEDIUM,
            summary="Support both import styles by providing both named and default exports.",
            problem="Import mismatch - importing { Component } but file uses export default.",
            solution="""Support BOTH named and default exports:

export function Button({ children, ...props }) {
  return <button {...props}>{children}</button>;
}
export default Button;  // Also provide default export""",
            tags=["react", "exports", "imports"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="API function naming - provide aliases",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.MEDIUM,
            summary="Provide both primary function and common aliases in api.js.",
            problem="Page imports getFlights but api.js exports searchFlights.",
            solution="""Provide both aliases in api.js:

export async function searchFlights(params) { ... }
export const getFlights = searchFlights;  // Alias
export const fetchFlights = searchFlights;  // Another alias
export const listFlights = searchFlights;  // Another alias""",
            tags=["react", "api", "naming"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Create response unwrap utility",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.HIGH,
            summary="Create utility to unwrap API responses with various wrapper formats.",
            problem="UI shows empty because backend returns wrapped response but frontend expects different format.",
            solution="""Create unwrap utility:

// utils/unwrap.js
export function unwrapResponse(response) {
    const data = response.data;
    
    if (data?.data) return data.data;       // { data: {...} }
    if (data?.items) return data.items;      // { items: [...] }
    if (data?.cart) return data.cart;        // { cart: {...} }
    
    // Single-key wrapper pattern
    const keys = Object.keys(data || {});
    if (keys.length === 1 && typeof data[keys[0]] === 'object') {
        return data[keys[0]];
    }
    
    return data;
}""",
            tags=["react", "api", "response-handling"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="CartContext must check token before API calls",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.HIGH,
            summary="Guard authenticated API calls in CartContext - skip if no token.",
            problem="Guest users see 401 errors because CartContext calls /api/cart without checking auth.",
            symptoms=[
                "GET /api/cart 401 on page load",
                "Console errors for unauthenticated users"
            ],
            solution="""Guard cart API calls:

const refreshCart = async () => {
    const token = localStorage.getItem('token');
    
    // CRITICAL: Skip API call if no token
    if (!token) {
        setItems([]);
        setTotal(0);
        return;
    }
    
    try {
        const response = await getCart();
        setItems(response?.items || []);
    } catch (error) {
        if (error.response?.status === 401) {
            setItems([]);
            localStorage.removeItem('token');
        }
    }
};""",
            tags=["react", "auth", "cart", "context"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="ScrollRestoration requires Data Router - use custom component",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.MEDIUM,
            summary="ScrollRestoration only works with createBrowserRouter, not BrowserRouter.",
            problem="Using ScrollRestoration from react-router-dom causes crash.",
            solution="""Use custom ScrollToTop component:

// components/layout/ScrollToTop.jsx
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export function ScrollToTop() {
    const { pathname } = useLocation();
    
    useEffect(() => {
        window.scrollTo(0, 0);
    }, [pathname]);
    
    return null;
}

// In App.jsx:
<BrowserRouter>
    <ScrollToTop />
    <Routes>...</Routes>
</BrowserRouter>""",
            tags=["react", "router", "scroll"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Defensive data handling prevents React crashes",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.HIGH,
            summary="Always guard .map() calls and check Array.isArray before rendering lists.",
            problem="Page crashes with React error #31 when API returns 404 or unexpected format.",
            symptoms=[
                "Minified React error #31",
                "Cannot read property 'map' of undefined"
            ],
            solution="""Always use defensive patterns:

const [items, setItems] = useState([]);
const [loading, setLoading] = useState(true);
const [error, setError] = useState(null);

useEffect(() => {
    api.getItems()
        .then(data => {
            setItems(Array.isArray(data) ? data : data?.items || []);
        })
        .catch(setError)
        .finally(() => setLoading(false));
}, []);

// In render:
{loading && <Spinner />}
{error && <EmptyState message="Could not load" />}
{Array.isArray(items) && items.map(i => <Item key={i.id} {...i} />)}""",
            tags=["react", "error-handling", "defensive"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Slug vs UUID - resolve entity first for dependent calls",
            category=KnowledgeCategory.REACT_PATTERN,
            severity=Severity.HIGH,
            summary="When route uses slug but APIs need UUID, fetch main entity first.",
            problem="Detail page loads but cast/showtimes fail with uuid parse error.",
            root_cause="Frontend passes URL slug directly to APIs expecting UUID.",
            solution="""Resolve entity first, then use its ID:

const { slug } = useParams();
const [movie, setMovie] = useState(null);
const [cast, setCast] = useState([]);

// Step 1: Fetch movie by slug to get UUID
useEffect(() => {
    api.getMovie(slug).then(setMovie);
}, [slug]);

// Step 2: Use movie.id (UUID) for dependent calls
useEffect(() => {
    if (!movie?.id) return;  // Wait for movie
    api.getMovieCast(movie.id).then(setCast);
}, [movie?.id]);""",
            tags=["react", "api", "slug", "uuid"],
            applies_to=["frontend"]
        ),

        # =====================================================================
        # UI/UX PATTERNS (from ui-ux-pro-max-skill)
        # =====================================================================
        Knowledge(
            title="Color palette should have clear hierarchy",
            category=KnowledgeCategory.UI_STYLE,
            severity=Severity.MEDIUM,
            summary="Use a dominant primary color with 1-2 accent colors. Avoid evenly distributed palettes.",
            content="""Good color hierarchy:
- Primary: Main actions, key UI elements (60%)
- Secondary: Supporting elements (30%)
- Accent: Highlights, notifications (10%)

Define CSS variables for consistency:
--color-primary: #...
--color-primary-hover: #...
--color-secondary: #...
--color-accent: #...
--color-background: #...
--color-surface: #...""",
            tags=["ui", "colors", "design-system", "tailwind"],
            source="ui-ux-pro-max-skill",
            source_url="https://github.com/nextlevelbuilder/ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Typography hierarchy with distinct weights and sizes",
            category=KnowledgeCategory.UI_STYLE,
            severity=Severity.MEDIUM,
            summary="Establish clear typographic hierarchy with headings, body, and caption styles.",
            content="""Typography scale:
- Display: 48-72px, bold (hero sections)
- H1: 36-48px, semibold
- H2: 24-36px, semibold
- H3: 20-24px, medium
- Body: 16px, regular
- Small: 14px, regular
- Caption: 12px, regular

Font recommendations:
- Headings: Space Grotesk, Clash Display, Satoshi
- Body: Inter, DM Sans, Plus Jakarta Sans
- Avoid: Arial, system fonts for display""",
            tags=["ui", "typography", "fonts", "design-system"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Consistent spacing scale",
            category=KnowledgeCategory.UI_STYLE,
            severity=Severity.LOW,
            summary="Apply consistent spacing using a base unit (4px or 8px) multiplied systematically.",
            content="""Spacing scale (4px base):
- xs: 4px (1)
- sm: 8px (2)
- md: 16px (4)
- lg: 24px (6)
- xl: 32px (8)
- 2xl: 48px (12)

Apply consistently:
- Component padding: md-lg
- Between related items: sm-md
- Between sections: xl-2xl
- Page margins: lg-xl""",
            tags=["ui", "spacing", "design-system", "tailwind"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Card components need visual hierarchy",
            category=KnowledgeCategory.UI_COMPONENT,
            severity=Severity.MEDIUM,
            summary="Cards should have clear structure: image/media, title, metadata, actions.",
            content="""Card structure:
1. Media (image, video) - top, with aspect ratio
2. Content area with padding
   - Title (prominent, truncate if long)
   - Subtitle/description (muted, line-clamp)
   - Metadata (tags, date, etc)
3. Actions (buttons, links) - bottom or overlay""",
            example_code="""<div class="group overflow-hidden rounded-lg bg-surface transition-shadow hover:shadow-lg">
    <div class="aspect-video overflow-hidden">
        <img class="h-full w-full object-cover transition-transform group-hover:scale-105" />
    </div>
    <div class="p-4">
        <h3 class="line-clamp-1 font-semibold">Title</h3>
        <p class="mt-1 line-clamp-2 text-sm text-muted">Description...</p>
        <div class="mt-3 flex items-center justify-between">
            <span class="text-primary font-medium">$99</span>
            <button class="text-sm">Action</button>
        </div>
    </div>
</div>""",
            tags=["ui", "components", "cards", "tailwind"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Loading states should use skeletons not spinners",
            category=KnowledgeCategory.UI_COMPONENT,
            severity=Severity.LOW,
            summary="Use skeleton screens that match content layout rather than generic spinners.",
            content="""Skeleton benefits:
- Shows expected layout
- Feels faster than spinner
- Reduces layout shift""",
            example_code="""// Skeleton component
<div class="animate-pulse space-y-3">
    <div class="h-48 rounded-lg bg-gray-700"></div>
    <div class="h-4 w-3/4 rounded bg-gray-700"></div>
    <div class="h-3 w-1/2 rounded bg-gray-700"></div>
</div>""",
            tags=["ui", "loading", "skeleton", "ux"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Empty states should guide user action",
            category=KnowledgeCategory.UI_COMPONENT,
            severity=Severity.LOW,
            summary="Empty states should explain what goes here and provide action to add content.",
            content="""Empty state components:
1. Icon or illustration
2. Title explaining what's missing
3. Description with context
4. CTA button to add/create""",
            example_code="""<div class="flex flex-col items-center justify-center py-12 text-center">
    <ShoppingBag class="h-12 w-12 text-muted" />
    <h3 class="mt-4 font-semibold">Your cart is empty</h3>
    <p class="mt-2 text-sm text-muted">Start shopping to add items</p>
    <Button class="mt-4" onClick={goToShop}>Browse Products</Button>
</div>""",
            tags=["ui", "empty-state", "ux", "components"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Form inputs need clear feedback states",
            category=KnowledgeCategory.UI_COMPONENT,
            severity=Severity.MEDIUM,
            summary="Form inputs should have distinct states: default, focus, error, success, disabled.",
            example_code="""<div class="space-y-1">
    <label class="text-sm font-medium">
        Email <span class="text-red-500">*</span>
    </label>
    <input 
        class="w-full rounded-lg border border-gray-600 bg-surface px-3 py-2
               focus:border-primary focus:ring-2 focus:ring-primary/20
               aria-invalid:border-red-500"
    />
    {error && <p class="text-sm text-red-500">{error}</p>}
</div>""",
            tags=["ui", "forms", "inputs", "validation"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        Knowledge(
            title="Responsive design breakpoints - mobile first",
            category=KnowledgeCategory.UI_RESPONSIVE,
            severity=Severity.MEDIUM,
            summary="Use mobile-first approach with consistent breakpoint system.",
            content="""Tailwind breakpoints:
- sm: 640px (large phones)
- md: 768px (tablets)
- lg: 1024px (laptops)
- xl: 1280px (desktops)
- 2xl: 1536px (large screens)

Mobile-first: default styles for mobile, add complexity at larger breakpoints.""",
            example_code="""<!-- Mobile: 1 col, Tablet: 2 col, Desktop: 4 col -->
<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
    ...
</div>

<!-- Mobile: stack, Desktop: side-by-side -->
<div class="flex flex-col lg:flex-row lg:gap-8">
    <aside class="lg:w-64">Sidebar</aside>
    <main class="flex-1">Content</main>
</div>""",
            tags=["ui", "responsive", "mobile-first", "tailwind"],
            source="ui-ux-pro-max-skill",
            applies_to=["frontend"]
        ),

        # =====================================================================
        # BACKEND PATTERNS
        # =====================================================================
        Knowledge(
            title="Dockerfile native module build failures",
            category=KnowledgeCategory.DOCKER,
            severity=Severity.HIGH,
            summary="Add build dependencies in Alpine Dockerfile for bcrypt and native modules.",
            problem="npm install fails with bcrypt compilation errors in Alpine.",
            solution="""Add build dependencies in Dockerfile:
RUN apk add --no-cache python3 make g++
RUN npm install --omit=dev --legacy-peer-deps""",
            tags=["docker", "bcrypt", "alpine", "npm"],
            applies_to=["backend"]
        ),

        Knowledge(
            title="ESLint flat config for ES modules",
            category=KnowledgeCategory.CONFIG,
            severity=Severity.MEDIUM,
            summary="Use eslint.config.js flat config, NOT .eslintrc for ES module projects.",
            problem="ESLint fails with 'type: module' packages.",
            example_code="""// eslint.config.js
import js from '@eslint/js';
import globals from 'globals';

export default [
    js.configs.recommended,
    {
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'module',
            globals: {
                ...globals.node,  // Adds process, console, etc.
            }
        }
    }
];""",
            tags=["eslint", "config", "esm", "node"],
            applies_to=["backend", "frontend"]
        ),

        Knowledge(
            title="UUID vs Slug parameter handling",
            category=KnowledgeCategory.EXPRESS_PATTERN,
            severity=Severity.HIGH,
            summary="Routes must detect and handle both UUID and slug parameters.",
            problem="Route accepts slug but query expects UUID, causing 'invalid input syntax for type uuid'.",
            example_code="""const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

router.get('/:idOrSlug', async (req, res) => {
    const { idOrSlug } = req.params;
    const isUUID = UUID_RE.test(idOrSlug);
    
    const query = isUUID 
        ? 'SELECT * FROM movies WHERE id = $1::uuid'
        : 'SELECT * FROM movies WHERE slug = $1::text';
    
    const result = await pool.query(query, [idOrSlug]);
    // ...
});""",
            tags=["backend", "express", "uuid", "slug", "routing"],
            applies_to=["backend"]
        ),

        Knowledge(
            title="Date objects serialize as empty {} in JSON",
            category=KnowledgeCategory.EXPRESS_PATTERN,
            severity=Severity.HIGH,
            summary="JavaScript Date objects serialize to {} - convert to ISO strings.",
            problem="Frontend crashes with React error #31 - dates appear as {} in JSON.",
            root_cause="toCamel() utility treats Date as plain object.",
            solution="""Handle Date in serialization:

const formatValue = (v) => {
    if (v instanceof Date) {
        return isNaN(v.getTime()) ? null : v.toISOString();
    }
    return v;
};

export const toCamel = (value) => {
    if (value instanceof Date) return formatValue(value);
    if (!isPlainObject(value)) return value;
    // ... rest
};""",
            tags=["backend", "serialization", "date", "json"],
            applies_to=["backend"]
        ),

        Knowledge(
            title="Docker compose service dependencies with healthcheck",
            category=KnowledgeCategory.DOCKER,
            severity=Severity.HIGH,
            summary="Use depends_on with condition: service_healthy for proper startup order.",
            problem="Backend starts before database is ready, causing connection errors.",
            example_code="""services:
  database:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
  
  backend:
    depends_on:
      database:
        condition: service_healthy""",
            tags=["docker", "docker-compose", "healthcheck"],
            applies_to=["database", "backend"]
        ),

        Knowledge(
            title="requireAuth must verify user exists in DB",
            category=KnowledgeCategory.EXPRESS_PATTERN,
            severity=Severity.HIGH,
            summary="Auth middleware should check user still exists, not just decode JWT.",
            problem="JWT token contains user_id that no longer exists → FK violations.",
            solution="""Add user existence check in requireAuth:

const decoded = jwt.verify(token, process.env.JWT_SECRET);

// CRITICAL: Verify user exists in DB!
const { rows } = await query(
    'SELECT id, email FROM users WHERE id = $1',
    [decoded.sub || decoded.id]
);
if (rows.length === 0) {
    return res.status(401).json({ error: 'User no longer exists' });
}

req.user = rows[0];  // Use fresh DB data
next();""",
            tags=["backend", "auth", "jwt", "middleware"],
            applies_to=["backend"]
        ),

        # =====================================================================
        # FRONTEND - Docker/nginx
        # =====================================================================
        Knowledge(
            title="Production Dockerfile must be multi-stage",
            category=KnowledgeCategory.DOCKER,
            severity=Severity.HIGH,
            summary="Frontend needs multi-stage Dockerfile for production builds.",
            problem="Docker build fails with 'Cannot locate Dockerfile' or service has no image.",
            example_code="""# app/frontend/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]""",
            tags=["docker", "frontend", "nginx", "production"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="nginx.conf must proxy /api before SPA catch-all route",
            category=KnowledgeCategory.DOCKER,
            severity=Severity.CRITICAL,
            summary="nginx /api location must be defined BEFORE / location.",
            problem="API calls return index.html because SPA catch-all routing catches everything.",
            example_code="""server {
    listen 3000;
    root /usr/share/nginx/html;
    
    # API proxy MUST come FIRST
    location /api {
        proxy_pass http://backend:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
    
    # SPA catch-all route comes SECOND
    location / {
        try_files $uri $uri/ /index.html;
    }
}""",
            tags=["nginx", "docker", "frontend", "api-proxy"],
            applies_to=["frontend"]
        ),

        Knowledge(
            title="nginx proxy_pass port must match backend internal port",
            category=KnowledgeCategory.DOCKER,
            severity=Severity.HIGH,
            summary="nginx.conf proxy_pass must use backend's actual PORT, not compose mapping.",
            problem="API calls return 502 Bad Gateway.",
            root_cause="nginx.conf has proxy_pass http://backend:3000 but backend listens on 8083.",
            solution="""Check backend's PORT and match in nginx.conf:

location /api {
    proxy_pass http://backend:8083;  # Must match backend PORT env/Dockerfile
}

Verify: docker compose logs backend | grep 'listening'""",
            tags=["nginx", "docker", "proxy", "ports"],
            applies_to=["frontend", "backend"]
        ),
    ]


def seed_knowledge(store: KnowledgeStore = None) -> int:
    """
    Seed the knowledge store with initial entries.
    
    Args:
        store: Optional KnowledgeStore instance.
    
    Returns:
        Number of entries added
    """
    if store is None:
        store = KnowledgeStore(db_url=KnowledgeStore.default_sqlite_url())
    
    entries = get_seed_knowledge()
    
    for k in entries:
        store.add(k)
    
    return len(entries)


if __name__ == "__main__":
    count = seed_knowledge()
    print(f"Seeded {count} knowledge entries to knowledge database")
