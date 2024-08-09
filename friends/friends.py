from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from api.dependencies.authenticated import get_user_dep
from tools.db import db as mongoDB
from crud.user import get_user_email_or_username
from tools import r, send_email, insecure_cols
from bson import ObjectId
from pydantic import BaseModel
import datetime

router = APIRouter(
    tags=["Friends Extension"],
    dependencies=[Depends(get_user_dep)],
)

friends_collection = mongoDB.get_collection("friends")

hide_friends_fields = {"sender._id": 0, "receiver._id": 0}
for col in insecure_cols:
    hide_friends_fields[f"sender.{col}"] = 0
    hide_friends_fields[f"receiver.{col}"] = 0


def aggregate_friends(user_id, pending: bool = None):
    return list(
        friends_collection.aggregate(
            [
                {
                    "$match": {
                        "pending": pending,
                        "$or": [
                            {"sender_id": ObjectId(user_id)},
                            {"receiver_id": ObjectId(user_id)},
                        ],
                    }
                },
                {
                    "$lookup": {
                        "from": "users",
                        "localField": "sender_id",
                        "foreignField": "_id",
                        "as": "sender",
                    }
                },
                {
                    "$lookup": {
                        "from": "users",
                        "localField": "receiver_id",
                        "foreignField": "_id",
                        "as": "receiver",
                    }
                },
                {"$unwind": {"path": "$sender"}},
                {"$unwind": {"path": "$receiver"}},
                {"$project": hide_friends_fields},
                {
                    "$project": {
                        "sender": 1,
                        "receiver": 1,
                        "request_id": {"$toString": "$_id"},
                        "_id": 0,
                    }
                },
            ]
        )
    )


@router.get("")
async def friends(user: dict = Depends(get_user_dep)):
    """
    # Get Friends

    ## Description
    This endpoint is used to get the friends of a user.
    """
    return aggregate_friends(user["_id"])


@router.get("/requests")
async def friend_requests(user: dict = Depends(get_user_dep)):
    """
    # Ingoing and Outgoing Friend Requests

    ## Description
    This endpoint is used to get the ingoing and outgoing friend requests of the user.
    Useful to accept or decline friend requests / cancel friend requests.
    Only returns friend requests, not friends.
    """
    frds = aggregate_friends(user["_id"], True)
    outgoing = []
    ingoing = []
    # ID is not visible in the response so we compare usernames (also unique)
    for frd in frds:
        if frd["sender"]["username"] == user["username"]:
            outgoing.append(frd)
        else:
            ingoing.append(frd)
    return {"outgoing": outgoing, "ingoing": ingoing}


class FriendRequestAccept(BaseModel):
    request_id: str


class FriendRequest(BaseModel):
    identifier: str


@router.post("/add")
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
        {"sender_id": user["_id"], "receiver_id": friend["_id"]}
    ) or friends_collection.count_documents(
        {"sender_id": friend["_id"], "receiver_id": user["_id"]}
    ):
        raise HTTPException(status_code=400, detail="Friend (request) already exists.")
    result = friends_collection.insert_one(
        {
            "sender_id": ObjectId(user["_id"]),
            "receiver_id": ObjectId(friend["_id"]),
            "pending": True,
            "requestedAt": datetime.datetime.now(),
        }
    )
    background_tasks.add_task(
        send_email, "FriendRequest", friend["email"], username=user["username"]
    )
    return FriendRequestAccept(request_id=str(result.inserted_id))


@router.post("/accept", status_code=204)
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
            "receiver_id": ObjectId(user["_id"]),
            "pending": True,
        },
        {
            "$set": {
                "acceptedAt": datetime.datetime.now(),
            },
            "$unset": {"pending": ""},
        },
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Friend request not found.")


@router.delete("/remove", status_code=204)
async def delete_friend(
    req: FriendRequestAccept,
    user: dict = Depends(get_user_dep),
):
    """
    # Delete Friend Request / Delete Friend

    ## Description
    This endpoint is used to decline a friend request.

    Or to delete a friend, or delete a friend request.
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
                {"sender_id": ObjectId(user["_id"])},
                {"receiver_id": ObjectId(user["_id"])},
            ],
        }
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Friend (request) not found.")
