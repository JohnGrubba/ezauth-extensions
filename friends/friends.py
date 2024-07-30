from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from api.dependencies.authenticated import get_user_dep
from tools.db import db as mongoDB
from crud.user import get_user_email_or_username
from tools import r, send_email
from bson import ObjectId
from pydantic import BaseModel

router = APIRouter(
    tags=["Friends Extension"],
    dependencies=[Depends(get_user_dep)],
)

friends_collection = mongoDB.get_collection("friends")


@router.get("")
async def friends(user: dict = Depends(get_user_dep)):
    """
    # Get Friends

    ## Description
    This endpoint is used to get the friends of a user.
    """
    return list(
        friends_collection.find(
            {
                "$or": [
                    {"user_id": ObjectId(user["_id"])},
                    {"friend_id": ObjectId(user["_id"])},
                ],
                "pending": False,
            },
            {
                "request_id": {"$toString": "$_id"},
                "user_id": {"$toString": "$user_id"},
                "friend_id": {"$toString": "$friend_id"},
                "_id": 0,
            },
        )
    )


@router.get("/requests")
async def friend_requests(user: dict = Depends(get_user_dep)):
    """
    # Ingoing and Outgoing Friend Requests

    ## Description
    This endpoint is used to get the ingoing and outgoing friend requests of the user.
    Useful to accept or decline friend requests / cancel friend requests.
    Only returns friend requests, not friends.
    """
    return list(
        friends_collection.find(
            {
                "$or": [
                    {"user_id": ObjectId(user["_id"])},
                    {"friend_id": ObjectId(user["_id"])},
                ],
                "pending": True,
            },
            {
                "request_id": {"$toString": "$_id"},
                "user_id": {"$toString": "$user_id"},
                "friend_id": {"$toString": "$friend_id"},
                "_id": 0,
            },
        )
    )


class FriendRequestAccept(BaseModel):
    request_id: str


class FriendRequest(BaseModel):
    identifier: str


@router.post("/add/{identifier}")
async def add_friend(
    req: FriendRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_user_dep),
):
    """
    # Add Friend

    ## Description
    This endpoint is used to add a friend to the user.
    """
    # Search friend in users collection by username
    friend = get_user_email_or_username(req.identifier)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found.")
    if friend["_id"] == user["_id"]:
        raise HTTPException(
            status_code=400, detail="You should already be friends with yourself :)"
        )
    # Check if friend request already exists
    if friends_collection.count_documents(
        {"user_id": user["_id"], "friend_id": friend["_id"]}
    ) or friends_collection.count_documents(
        {"user_id": friend["_id"], "friend_id": user["_id"]}
    ):
        raise HTTPException(status_code=400, detail="Friend request already exists.")
    result = friends_collection.insert_one(
        {
            "user_id": ObjectId(user["_id"]),
            "friend_id": ObjectId(friend["_id"]),
            "pending": True,
        }
    )
    background_tasks.add_task(
        send_email, "FriendRequest", friend["email"], username=user["username"]
    )
    return FriendRequestAccept(request_id=result.inserted_id)


@router.post("/accept/", status_code=204)
async def accept_friend_request(
    req: FriendRequestAccept,
    user: dict = Depends(get_user_dep),
):
    """
    # Accept Friend Request

    ## Description
    This endpoint is used to accept a friend request.
    """
    try:
        ObjectId(req.request_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid ID.")
    # Get friend request (and check if it belongs to the user)
    result = friends_collection.update_one(
        {
            "_id": ObjectId(req.request_id),
            "$or": [
                {"user_id": ObjectId(user["_id"])},
                {"friend_id": ObjectId(user["_id"])},
            ],
        },
        {"$set": {"pending": False}},
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Friend request not found.")


@router.post("/decline/", status_code=204)
async def decline_friend_request(
    req: FriendRequestAccept,
    user: dict = Depends(get_user_dep),
):
    """
    # Decline Friend Request

    ## Description
    This endpoint is used to decline a friend request.
    """
    try:
        ObjectId(req.request_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid ID.")
    # Get friend request (and check if it belongs to the user)
    result = friends_collection.delete_one(
        {
            "_id": ObjectId(req.request_id),
            "$or": [
                {"user_id": ObjectId(user["_id"])},
                {"friend_id": ObjectId(user["_id"])},
            ],
        }
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Friend request not found.")
