"""
Schema Catalog - Whitelist duy nhất cho text-to-SQL.
LLM chỉ được query các bảng/cột được khai báo ở đây.
"""

from typing import Literal, TypedDict


class ColumnDef(TypedDict, total=False):
    type: str
    selectable: bool
    description: str


class TableDef(TypedDict):
    description: str
    columns: dict[str, ColumnDef]
    allowed_filters: list[str]
    allowed_order_by: list[str]
    forbidden_columns: list[str]  # double-check runtime


class JoinDef(TypedDict):
    from_table: str
    to_table: str
    on: str
    description: str


class QueryExample(TypedDict):
    nl: str  # natural language
    query: dict  # structured query


SCHEMA_CATALOG = {
    "tables": {
        "users": {
            "description": "Người dùng hệ thống. KHÔNG select email/password_hash.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key user.",
                },
                "username": {
                    "type": "string",
                    "selectable": True,
                    "description": "Tên đăng nhập duy nhất.",
                },
                "full_name": {
                    "type": "string",
                    "selectable": True,
                    "description": "Họ tên đầy đủ.",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo tài khoản.",
                },
                # Forbidden columns - khai báo để validator check, nhưng selectable=False
                "email": {
                    "type": "string",
                    "selectable": False,
                    "description": "Email (FORBIDDEN).",
                },
                "password_hash": {
                    "type": "string",
                    "selectable": False,
                    "description": "Password hash (FORBIDDEN).",
                },
            },
            "allowed_filters": ["id", "username", "created_at"],
            "allowed_order_by": ["created_at", "username"],
            "forbidden_columns": ["email", "password_hash"],
        },
        "quizzes": {
            "description": "Bộ câu hỏi (quiz). is_public=true mới hiện trong search công khai.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key quiz.",
                },
                "title": {
                    "type": "string",
                    "selectable": True,
                    "description": "Tiêu đề quiz.",
                },
                "description": {
                    "type": "string",
                    "selectable": True,
                    "description": "Mô tả ngắn nội dung quiz.",
                },
                "is_public": {
                    "type": "bool",
                    "selectable": True,
                    "description": "True = công khai cho mọi người.",
                },
                "is_deleted": {
                    "type": "bool",
                    "selectable": True,
                    "description": "Soft delete. Luôn filter is_deleted=false.",
                },
                "created_by": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id (người tạo).",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo quiz.",
                },
                "updated_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Lần cập nhật cuối.",
                },
            },
            "allowed_filters": [
                "is_public",
                "is_deleted",
                "created_by",
                "created_at",
                "updated_at",
            ],
            "allowed_order_by": ["created_at", "updated_at", "title"],
            "forbidden_columns": [],
        },
        "questions": {
            "description": "Câu hỏi trong quiz. Phải join với quizzes để biết is_public.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key question.",
                },
                "quiz_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> quizzes.id.",
                },
                "content": {
                    "type": "string",
                    "selectable": True,
                    "description": "Nội dung câu hỏi.",
                },
                "question_type": {
                    "type": "enum",
                    "selectable": True,
                    "description": "single_choice | multiple_choice | true_false",
                },
                "points": {
                    "type": "int",
                    "selectable": True,
                    "description": "Điểm số của câu hỏi.",
                },
                "time_limit": {
                    "type": "int",
                    "selectable": True,
                    "description": "Giới hạn thời gian (giây).",
                },
                "order_index": {
                    "type": "int",
                    "selectable": True,
                    "description": "Thứ tự câu hỏi trong quiz.",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo.",
                },
            },
            "allowed_filters": [
                "quiz_id",
                "question_type",
                "points",
                "created_at",
            ],
            "allowed_order_by": ["order_index", "created_at", "points"],
            "forbidden_columns": [],
        },
        "game_rooms": {
            "description": "Phòng chơi game. ended_at IS NULL = đang mở.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key room.",
                },
                "room_code": {
                    "type": "string",
                    "selectable": True,
                    "description": "Mã phòng duy nhất (6-10 ký tự).",
                },
                "quiz_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> quizzes.id.",
                },
                "host_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id (người host).",
                },
                "status": {
                    "type": "enum",
                    "selectable": True,
                    "description": "waiting | playing | ended",
                },
                "max_players": {
                    "type": "int",
                    "selectable": True,
                    "description": "Số lượng người chơi tối đa.",
                },
                "started_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm bắt đầu game.",
                },
                "ended_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm kết thúc. NULL = chưa kết thúc.",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo phòng.",
                },
            },
            "allowed_filters": [
                "status",
                "host_id",
                "quiz_id",
                "created_at",
                "ended_at",
            ],
            "allowed_order_by": ["created_at", "started_at"],
            "forbidden_columns": [],
        },
        "user_stats": {
            "description": "Thống kê của từng user (tổng trận, điểm, tỷ lệ thắng).",
            "columns": {
                "user_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id (PK).",
                },
                "total_games": {
                    "type": "int",
                    "selectable": True,
                    "description": "Tổng số trận đã chơi.",
                },
                "total_score": {
                    "type": "int",
                    "selectable": True,
                    "description": "Tổng điểm tích lũy.",
                },
                "avg_score": {
                    "type": "float",
                    "selectable": True,
                    "description": "Điểm trung bình mỗi trận.",
                },
                "wins": {
                    "type": "int",
                    "selectable": True,
                    "description": "Số trận thắng.",
                },
                "updated_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Lần cập nhật stats cuối.",
                },
            },
            "allowed_filters": ["user_id", "total_games", "wins"],
            "allowed_order_by": ["total_score", "wins", "avg_score", "updated_at"],
            "forbidden_columns": [],
        },
        "game_results": {
            "description": "Kết quả game của từng user (điểm cuối, rank).",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key.",
                },
                "room_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> game_rooms.id.",
                },
                "user_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id.",
                },
                "final_score": {
                    "type": "int",
                    "selectable": True,
                    "description": "Điểm cuối cùng của user trong game.",
                },
                "rank": {
                    "type": "int",
                    "selectable": True,
                    "description": "Hạng (1=nhất, 2=nhì, ...).",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm ghi nhận kết quả.",
                },
            },
            "allowed_filters": ["room_id", "user_id", "rank", "created_at"],
            "allowed_order_by": ["final_score", "rank", "created_at"],
            "forbidden_columns": [],
        },
        "conversations": {
            "description": "Hội thoại chat (1-1 hoặc nhóm). Chỉ member mới truy vấn được.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key conversation.",
                },
                "type": {
                    "type": "enum",
                    "selectable": True,
                    "description": "direct | group",
                },
                "title": {
                    "type": "string",
                    "selectable": True,
                    "description": "Tiêu đề (group có, direct NULL).",
                },
                "last_message_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm message cuối.",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo conversation.",
                },
            },
            "allowed_filters": ["type", "created_at", "last_message_at"],
            "allowed_order_by": ["last_message_at", "created_at"],
            "forbidden_columns": ["direct_key"],  # internal key, không cần expose
        },
        "friendships": {
            "description": "Quan hệ bạn bè (2 chiều, không phân biệt requester).",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key.",
                },
                "user_id_1": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id (user thứ nhất).",
                },
                "user_id_2": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id (user thứ hai).",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm kết bạn.",
                },
            },
            "allowed_filters": ["user_id_1", "user_id_2", "created_at"],
            "allowed_order_by": ["created_at"],
            "forbidden_columns": [],
        },
        "tags": {
            "description": "Tags/nhãn cho quiz (Lịch sử, Toán học, Khoa học...).",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key tag.",
                },
                "name": {
                    "type": "string",
                    "selectable": True,
                    "description": "Tên tag (unique).",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo tag.",
                },
            },
            "allowed_filters": ["name", "created_at"],
            "allowed_order_by": ["name", "created_at"],
            "forbidden_columns": [],
        },
        "quizzes_tags": {
            "description": "Many-to-many: quiz <-> tag.",
            "columns": {
                "quiz_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> quizzes.id.",
                },
                "tag_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> tags.id.",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm gán tag.",
                },
            },
            "allowed_filters": ["quiz_id", "tag_id"],
            "allowed_order_by": ["created_at"],
            "forbidden_columns": [],
        },
        "user_achievements": {
            "description": "Thành tích/achievement của user.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key.",
                },
                "user_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id.",
                },
                "achievement_type": {
                    "type": "string",
                    "selectable": True,
                    "description": "Loại achievement (first_win, streak_7, etc).",
                },
                "achieved_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm đạt được.",
                },
            },
            "allowed_filters": ["user_id", "achievement_type", "achieved_at"],
            "allowed_order_by": ["achieved_at"],
            "forbidden_columns": [],
        },
        "notifications": {
            "description": "Thông báo của user (friend request, game invite, etc).",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key.",
                },
                "user_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id (người nhận).",
                },
                "type": {
                    "type": "string",
                    "selectable": True,
                    "description": "Loại thông báo.",
                },
                "title": {
                    "type": "string",
                    "selectable": True,
                    "description": "Tiêu đề ngắn.",
                },
                "is_read": {
                    "type": "bool",
                    "selectable": True,
                    "description": "Đã đọc chưa.",
                },
                "created_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm tạo thông báo.",
                },
            },
            "allowed_filters": ["user_id", "type", "is_read", "created_at"],
            "allowed_order_by": ["created_at"],
            "forbidden_columns": [],
        },
        "room_players": {
            "description": "Người chơi trong phòng game.",
            "columns": {
                "id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "Primary key.",
                },
                "room_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> game_rooms.id.",
                },
                "user_id": {
                    "type": "uuid",
                    "selectable": True,
                    "description": "FK -> users.id.",
                },
                "joined_at": {
                    "type": "datetime",
                    "selectable": True,
                    "description": "Thời điểm vào phòng.",
                },
                "is_ready": {
                    "type": "bool",
                    "selectable": True,
                    "description": "Đã sẵn sàng chưa.",
                },
            },
            "allowed_filters": ["room_id", "user_id", "is_ready", "joined_at"],
            "allowed_order_by": ["joined_at"],
            "forbidden_columns": [],
        },
    },
    "joins": {
        "quizzes__questions": {
            "from_table": "quizzes",
            "to_table": "questions",
            "on": "quizzes.id = questions.quiz_id",
            "description": "Lấy câu hỏi kèm thông tin quiz.",
        },
        "quizzes__game_rooms": {
            "from_table": "quizzes",
            "to_table": "game_rooms",
            "on": "quizzes.id = game_rooms.quiz_id",
            "description": "Lấy phòng game của quiz.",
        },
        "users__user_stats": {
            "from_table": "users",
            "to_table": "user_stats",
            "on": "users.id = user_stats.user_id",
            "description": "Lấy thống kê kèm thông tin user.",
        },
        "users__friendships_1": {
            "from_table": "users",
            "to_table": "friendships",
            "on": "users.id = friendships.user_id_1",
            "description": "Lấy bạn bè của user (via user_id_1).",
        },
        "users__friendships_2": {
            "from_table": "users",
            "to_table": "friendships",
            "on": "users.id = friendships.user_id_2",
            "description": "Lấy bạn bè của user (via user_id_2).",
        },
        "game_rooms__game_results": {
            "from_table": "game_rooms",
            "to_table": "game_results",
            "on": "game_rooms.id = game_results.room_id",
            "description": "Lấy kết quả của từng user trong room.",
        },
        "users__game_results": {
            "from_table": "users",
            "to_table": "game_results",
            "on": "users.id = game_results.user_id",
            "description": "Lấy lịch sử kết quả game của user.",
        },
        "quizzes__tags": {
            "from_table": "quizzes",
            "to_table": "quizzes_tags",
            "on": "quizzes.id = quizzes_tags.quiz_id",
            "description": "Lấy tags của quiz.",
        },
        "tags__quizzes_tags": {
            "from_table": "tags",
            "to_table": "quizzes_tags",
            "on": "tags.id = quizzes_tags.tag_id",
            "description": "Lấy quiz có tag này.",
        },
        "users__achievements": {
            "from_table": "users",
            "to_table": "user_achievements",
            "on": "users.id = user_achievements.user_id",
            "description": "Lấy achievements của user.",
        },
        "users__notifications": {
            "from_table": "users",
            "to_table": "notifications",
            "on": "users.id = notifications.user_id",
            "description": "Lấy thông báo của user.",
        },
        "game_rooms__room_players": {
            "from_table": "game_rooms",
            "to_table": "room_players",
            "on": "game_rooms.id = room_players.room_id",
            "description": "Lấy người chơi trong phòng.",
        },
        "users__room_players": {
            "from_table": "users",
            "to_table": "room_players",
            "on": "users.id = room_players.user_id",
            "description": "Lấy phòng mà user tham gia.",
        },
    },
    "examples": [
        {
            "nl": "Top 5 user có nhiều trận thắng nhất",
            "query": {
                "tables": ["users", "user_stats"],
                "joins": ["users__user_stats"],
                "select": ["users.username", "users.full_name", "user_stats.wins"],
                "filters": [],
                "order_by": [{"column": "user_stats.wins", "direction": "DESC"}],
                "limit": 5,
            },
        },
        {
            "nl": "Có bao nhiêu quiz public được tạo trong 7 ngày qua",
            "query": {
                "tables": ["quizzes"],
                "joins": [],
                "select": ["COUNT(*) AS count"],
                "filters": [
                    {"column": "is_public", "op": "=", "value": True},
                    {"column": "is_deleted", "op": "=", "value": False},
                    {"column": "created_at", "op": ">=", "value": "<last_7_days>"},
                ],
                "order_by": [],
                "limit": 1,
            },
        },
        {
            "nl": "Liệt kê quiz của tôi có trên 10 câu hỏi",
            "query": {
                "tables": ["quizzes", "questions"],
                "joins": ["quizzes__questions"],
                "select": [
                    "quizzes.id",
                    "quizzes.title",
                    "COUNT(questions.id) AS question_count",
                ],
                "filters": [
                    {"column": "quizzes.created_by", "op": "=", "value": "<current_user_id>"},
                    {"column": "quizzes.is_deleted", "op": "=", "value": False},
                ],
                "group_by": ["quizzes.id", "quizzes.title"],
                "having": [{"column": "COUNT(questions.id)", "op": ">", "value": 10}],
                "order_by": [{"column": "question_count", "direction": "DESC"}],
                "limit": 20,
            },
        },
        {
            "nl": "Ai là host của phòng đang chơi quiz về Python",
            "query": {
                "tables": ["game_rooms", "quizzes", "users"],
                "joins": ["quizzes__game_rooms", "game_rooms__host"],  # giả định có join này
                "select": ["users.username", "game_rooms.room_code", "quizzes.title"],
                "filters": [
                    {"column": "game_rooms.status", "op": "=", "value": "playing"},
                    {"column": "quizzes.title", "op": "ILIKE", "value": "%Python%"},
                ],
                "order_by": [],
                "limit": 10,
            },
        },
    ],
}


# Enum whitelist cho validation
# Aggregate functions whitelist
ALLOWED_AGGREGATES = [
    "COUNT", "SUM", "AVG", "MIN", "MAX",
    "COUNT(*)",  # special case
]

# Date/time functions whitelist
ALLOWED_DATE_FUNCTIONS = [
    "DATE_TRUNC",  # DATE_TRUNC('day', created_at)
    "EXTRACT",     # EXTRACT(YEAR FROM created_at)
    "NOW",
    "CURRENT_DATE",
    "CURRENT_TIMESTAMP",
]

# Window functions (future support)
ALLOWED_WINDOW_FUNCTIONS = [
    "ROW_NUMBER",
    "RANK",
    "DENSE_RANK",
    "LAG",
    "LEAD",
]

ENUM_VALUES = {
    "question_type": ["single_choice", "multiple_choice", "true_false"],
    "game_room_status": ["waiting", "playing", "ended"],
    "conversation_type": ["direct", "group"],
    "sender_type": ["user", "ai", "system"],
    "friend_request_status": ["pending", "accepted", "rejected"],
}

# Validation limits
MAX_JOINS = 3  # tối đa 3 bảng JOIN
MAX_LIMIT = 50  # tối đa 50 rows
REQUIRE_LIMIT = True  # LIMIT bắt buộc


def get_schema_catalog() -> dict:
    """Trả về schema catalog đầy đủ."""
    return SCHEMA_CATALOG


def get_enum_values(enum_name: str) -> list[str] | None:
    """Lấy whitelist values của enum."""
    return ENUM_VALUES.get(enum_name)


def is_table_allowed(table_name: str) -> bool:
    """Check table có trong catalog không."""
    return table_name in SCHEMA_CATALOG["tables"]


def is_column_selectable(table_name: str, column_name: str) -> bool:
    """Check column có selectable không."""
    if not is_table_allowed(table_name):
        return False
    table = SCHEMA_CATALOG["tables"][table_name]
    col = table["columns"].get(column_name)
    if not col:
        return False
    return col.get("selectable", False)


def is_column_filterable(table_name: str, column_name: str) -> bool:
    """Check column có cho phép filter không."""
    if not is_table_allowed(table_name):
        return False
    table = SCHEMA_CATALOG["tables"][table_name]
    return column_name in table["allowed_filters"]


def is_forbidden_column(table_name: str, column_name: str) -> bool:
    """Check column có bị cấm không (double-check runtime)."""
    if not is_table_allowed(table_name):
        return True
    table = SCHEMA_CATALOG["tables"][table_name]
    return column_name in table.get("forbidden_columns", [])
