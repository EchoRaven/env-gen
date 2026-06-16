"""OAuth contract test scripts (one per upstream env).

Each ``test_<env>.py`` here is a runnable script that exercises the
8-test minimum OAuth contract from ``env-oauth-blueprint``:

    1. health and discovery
    2. register + login → JWT
    3. duplicate register rejected
    4. multi-tenant same-email distinct identities
    5. UI JWT works on resource server
    6. garbage token rejected
    7. expired token rejected
    8. wrong password rejected

Each script exits 0 on full pass, 1 on any failure, and takes
``<ENV>_API_URL`` as the URL to test against.
"""
