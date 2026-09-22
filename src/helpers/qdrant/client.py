from qdrant_client import QdrantClient
import os
import atexit  # مكتبة للتعامل مع أحداث نهاية البرنامج

_qdrant_client_instance = None

def get_qdrant_client():
    global _qdrant_client_instance

    if _qdrant_client_instance is None:
        storage_path = os.getenv(
            "QDRANT_STORAGE_PATH",
            "./qdrant_storage"
        )

        _qdrant_client_instance = QdrantClient(
            path=storage_path
        )

    return _qdrant_client_instance

# دالة لإغلاق الاتصال بأمان
def close_qdrant_client():
    global _qdrant_client_instance
    if _qdrant_client_instance is not None:
        _qdrant_client_instance.close()
        _qdrant_client_instance = None

# إجبار بايثون على استدعاء هذه الدالة قبل إغلاق البرنامج
atexit.register(close_qdrant_client)