# MovieHub Generation Issues Report
**Project**: Movie Ticketing Platform (Fandango-style)
**Date**: 2026-01-05
**Status**: FAILED (but 90%+ functional)

## Summary
Despite the generation ending with FAILED status, the project is largely functional:
- Frontend accessible at http://localhost:8080 ✅
- Backend API working at http://localhost:8083 ✅
- Database with 30 movies seeded ✅
- Docker containers running ✅

## Issues Discovered and Added to Known Issues

### Frontend Issues (6 new)

| # | Issue | Symptom | Solution | Added to known_issues.j2 |
|---|-------|---------|----------|--------------------------|
| 32 | ScrollRestoration requires Data Router | App crashes on load | Use custom ScrollToTop component instead | ✅ |
| 33 | API Error Handling (React Error #31) | Page crashes when API returns 404 | Add Array.isArray check, loading/error states | ✅ |
| 34 | Slug vs UUID mismatch | Cast/showtimes fail with 500 | Fetch movie first, use movie.id for dependent calls | ✅ |
| 35 | Missing dependencies | Docker build fails "Cannot resolve" | Check imports match package.json | ✅ |
| 36 | useEffect missing dependencies | Lint errors, infinite loops | Include all deps in dependency array | ✅ |
| - | react-hot-toast not installed | Build fails | Add to package.json dependencies | (covered by #35) |

### Backend Issues (5 new)

| # | Issue | Symptom | Solution | Added to known_issues.j2 |
|---|-------|---------|----------|--------------------------|
| 8 | bcrypt vs bcryptjs mismatch | Container crash ERR_MODULE_NOT_FOUND | Match import with package.json | ✅ |
| 9 | UUID vs Slug handling (pg 22P02) | 500 error "invalid input syntax for uuid" | Detect UUID format, use appropriate query | ✅ |
| 10 | Missing List endpoint (GET /) | 404 on list requests | Add router.get('/') with filters | ✅ |
| 11 | Nested routes don't support slug | /api/movies/:slug/cast fails | resolveMovieId helper function | ✅ |
| 12 | Docker cache shows stale code | Changes not reflected | Use --no-cache rebuild | ✅ |

### Database Issues (4 new)

| # | Issue | Symptom | Solution | Added to known_issues.j2 |
|---|-------|---------|----------|--------------------------|
| 12 | UUID type cast in INSERT | Type mismatch error | Use explicit ::uuid cast | ✅ |
| 13 | Incomplete seed relationships | Empty UI sections | Seed ALL related tables | ✅ |
| 14 | JOIN LATERAL syntax | Syntax error in complex seeds | Use CROSS JOIN LATERAL | ✅ |
| 15 | Missing slug column | Backend can't do slug lookups | Add slug column with index | ✅ |

## Root Cause Analysis

### Why Generation Failed
The generation ended at BackendAgent Step 15/30 while it was trying to implement the showtimes list endpoint. The agents were interrupted before completing all fixes.

### Key Integration Issues
1. **Frontend/Backend API Contract**: Frontend used slugs in URLs, backend expected UUIDs
2. **Missing Endpoints**: Backend lacked GET /api/showtimes list route
3. **Error Handling**: Frontend crashed when APIs returned errors instead of graceful degradation

### Docker Issues
1. Docker Desktop crashed/stopped twice during generation
2. Cache caused stale code issues requiring --no-cache rebuilds
3. npm ci vs npm install mismatch in Dockerfile

## Recommendations for Future Generations

### 1. API Contract Synchronization
- Add explicit slug support to ALL backend routes that accept entity IDs
- Frontend should always use resolved UUIDs for dependent API calls

### 2. Error Handling First
- Frontend pages MUST handle loading/error/empty states before rendering data
- Use `Array.isArray()` guards before `.map()` operations

### 3. Complete Endpoint Coverage
- Every entity needs: GET /, GET /:id, POST /, PUT /:id, DELETE /:id
- List endpoints MUST support common filters (date, foreign keys, etc.)

### 4. Docker Best Practices
- Always use `npm install` in Dockerfile (not `npm ci` without lock file)
- Include health checks in docker-compose for startup ordering
- Use `depends_on` with `condition: service_healthy`

## Files Modified

### Known Issues Files Updated:
- `multi_agent/prompts/agents/frontend/known_issues.j2` (+5 issues: #32-36)
- `multi_agent/prompts/agents/backend/known_issues.j2` (+5 issues: #8-12)
- `multi_agent/prompts/agents/database/known_issues.j2` (+4 issues: #12-15)

## Testing the Generated Project

```bash
# Check frontend
curl http://localhost:8080/

# Check movies API
curl http://localhost:8083/api/movies | jq '.data.items | length'
# Should return: 30

# Check specific movie by slug
curl http://localhost:8083/api/movies/neon-horizon

# Check theaters
curl http://localhost:8083/api/theaters
```

