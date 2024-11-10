# Friendships Extension for EZAuth

## Requirements
### E-Mail Templates
- `FriendRequest.html` E-Mail Template in the `config/email` folder.
    - `{{requestor_username}}` is the username of the user who sent the friend request.
    - `{{username}}` is the username of the user who received the friend request (the user who gets the email).
- `FriendRequestAccepted.html` E-Mail Template in the `config/email` folder. Gets sent to the user who sent the friend request when the request is accepted.
    - `{{acceptor_username}}` is the username of the user who accepted the request.
    - `{{username}}` is your own username. (The user who gets the email and sent the request)
- `FriendRequestRejected.html` E-Mail Template in the `config/email` folder. Gets sent to the user who sent the friend request when the request is rejected.
    - `{{decliner_username}}` is the username of the user who rejected the request.
    - `{{username}}` is your own username. (The user who gets the email and sent the request)


### Configuration
- `friend_add_timeout_seconds` - The timeout after a user can send another friend request to the same user after deleting the request. Default is 14 400 seconds (4 Hours).


## How does it Work?

### Friend Requests

- A user can send a friend request to another user. This is done by using the Username.
- The user who receives the friend request can either accept or reject the request.
- The user who receives the friend request will be notified that they have received a friend request.

### Accepting Requests

- The user who receives the friend request can accept the request. This will add the user to the friends list for both users.
- The user who sent the request will be notified that the request has been accepted.

### Rejecting Requests / Removing Friends

- Any Member of a Friendship can remove the other member from their friends list. This also works for rejecting friend requests.