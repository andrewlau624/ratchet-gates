# ruleid: ratchet-route-missing-auth-dependency
@router.get("/x")
async def get_x():
    return {"ok": True}
