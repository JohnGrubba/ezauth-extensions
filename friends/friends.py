from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from api.dependencies.authenticated import get_user_dep
from tools.db import db as mongoDB
from crud.user import get_user_identifier, get_user
from tools import queue_email, insecure_cols, r
from bson import ObjectId
from pydantic import BaseModel
import datetime
import json
import os

router = APIRouter(
    tags=["Friends Extension"],
    dependencies=[Depends(get_user_dep)],
)

script_dir = os.path.dirname(os.path.abspath(__file__))
friend_config = json.load(open(os.path.join(script_dir, "friends_conf.json"), "r"))
friends_collection = mongoDB.get_collection("friends")

hide_friends_fields = {}
for col in insecure_cols:
    hide_friends_fields[f"sender.{col}"] = 0
    hide_friends_fields[f"receiver.{col}"] = 0

# Redis DB for friend requests (used to check if request was sent before to avoid E-Mail spamming)
# Key: friend_request_{friend_id}
# Value: sender_id


def aggregate_friends(user_id, pending: bool = None, limit: int = 100, offset: int = 0):
    return friends_collection.aggregate(
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
            {
                "$addFields": {
                    "sender._id": {"$toString": "$sender._id"},
                    "receiver._id": {"$toString": "$receiver._id"},
                }
            },
            {"$skip": offset},
            {"$limit": limit},
        ]
    )


@router.get("")
async def friends(user: dict = Depends(get_user_dep)):
    """
    # Get Friends

    ## Description
    This endpoint is used to get the friends of a user.
    """
    return list(aggregate_friends(user["_id"]))


@router.get("/requests")
async def friend_requests(user: dict = Depends(get_user_dep)):
    """
    # Ingoing and Outgoing Friend Requests

    ## Description
    This endpoint is used to get the ingoing and outgoing friend requests of the user.
    Useful to accept or decline friend requests / cancel friend requests.
    Only returns friend requests, not friends.
    """
    frds = list(aggregate_friends(user["_id"], True))
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
    friend = get_user_identifier(req.identifier)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found.")
    if ObjectId(friend["_id"]) == ObjectId(user["_id"]):
        raise HTTPException(
            status_code=400, detail="You should already be friends with yourself :)"
        )
    # Check if friend request already exists
    if friends_collection.count_documents(
        {"sender_id": ObjectId(user["_id"]), "receiver_id": ObjectId(friend["_id"])}
    ) or friends_collection.count_documents(
        {"sender_id": ObjectId(friend["_id"]), "receiver_id": ObjectId(user["_id"])}
    ):
        raise HTTPException(status_code=400, detail="Friend (request) already exists.")

    prev_req = r.get(f"friend_request_{str(friend['_id'])}")
    if prev_req and prev_req == str(user["_id"]):
        raise HTTPException(
            status_code=429,
            detail="Slow Down. You already sent a friend request to this user previously. Please try again later.",
        )

    result = friends_collection.insert_one(
        {
            "sender_id": ObjectId(user["_id"]),
            "receiver_id": ObjectId(friend["_id"]),
            "pending": True,
            "requestedAt": datetime.datetime.now(),
        }
    )
    r.setex(
        f"friend_request_{str(friend['_id'])}",
        int(friend_config["friend_add_timeout_seconds"]),
        str(user["_id"]),
    )
    queue_email("FriendRequest", friend["email"], username=user["username"])
    return FriendRequestAccept(request_id=str(result.inserted_id))


@router.post("/accept", status_code=204)
async def accept_friend_request(
    req: FriendRequestAccept,
    background_tasks: BackgroundTasks,
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
    else:
        sender_usr = friends_collection.find_one(
            {
                "_id": ObjectId(req.request_id),
                "receiver_id": ObjectId(user["_id"]),
            }
        )
        sender_email = get_user(sender_usr["sender_id"])["email"]
        queue_email("FriendRequestAccepted", sender_email, username=user["username"])


@router.delete("/remove", status_code=204)
async def delete_friend(
    req: FriendRequestAccept,
    background_tasks: BackgroundTasks,
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
    # Only get a sender_user if the receiver rejects the request
    sender_usr = friends_collection.find_one(
        {
            "_id": ObjectId(req.request_id),
            "receiver_id": ObjectId(user["_id"]),
            "pending": True,
        }
    )
    if sender_usr:
        # Friend request was declined by other user (not deleted by user)
        sender_email = get_user(sender_usr["sender_id"])["email"]
        queue_email("FriendRequestRejected", sender_email, username=user["username"])
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
