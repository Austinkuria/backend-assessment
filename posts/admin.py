from django.contrib import admin

from .models import IdempotencyRecord, Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "author", "created_at", "version", "deleted_at"]
    list_filter = ["created_at", "deleted_at"]
    search_fields = ["title", "content", "author__username"]
    readonly_fields = ["created_at", "updated_at", "version"]

    def get_queryset(self, request):
        # Admins should also see soft-deleted posts.
        return Post.all_objects.select_related("author")


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ["key", "user", "response_status", "created_at"]
    search_fields = ["key", "user__username"]
    readonly_fields = ["user", "key", "request_fingerprint", "response_status", "response_body", "created_at"]
