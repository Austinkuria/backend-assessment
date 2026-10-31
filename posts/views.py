from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse

from . import idempotency, services
from .models import Post
from .permissions import IsAuthorOrReadOnly
from .serializers import PostSerializer


class PostViewSet(viewsets.ModelViewSet):
    """
    CRUD for posts.

    list:     GET    /api/posts/            (optional ?author=<user id>)
    create:   POST   /api/posts/            (requires Idempotency-Key header)
    retrieve: GET    /api/posts/{id}/
    update:   PUT    /api/posts/{id}/       (author only, optional If-Match)
    partial:  PATCH  /api/posts/{id}/       (author only, optional If-Match)
    destroy:  DELETE /api/posts/{id}/       (author only, optional If-Match)
    """

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated, IsAuthorOrReadOnly]
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        queryset = Post.objects.select_related("author")
        author = self.request.query_params.get("author")
        if author is not None:
            if not author.isdigit():
                raise ValidationError({"author": ["Must be a user id."]})
            queryset = queryset.filter(author_id=int(author))
        return queryset

    # Responses ----------------------------------------------------------

    def _post_response(self, post, status_code=status.HTTP_200_OK):
        return Response(self.get_serializer(post).data, status=status_code, headers={"ETag": post.etag})

    def _precondition_failed(self, current):
        return Response(
            {
                "detail": "This post has been modified since you last fetched it. "
                "Review the current version and retry with its ETag.",
                "current": self.get_serializer(current).data,
            },
            status=status.HTTP_412_PRECONDITION_FAILED,
            headers={"ETag": current.etag},
        )

    # Actions ------------------------------------------------------------

    def retrieve(self, request, *args, **kwargs):
        return self._post_response(self.get_object())

    def create(self, request, *args, **kwargs):
        key = idempotency.get_idempotency_key(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def publish():
            post = serializer.save(author=request.user)
            return status.HTTP_201_CREATED, self.get_serializer(post).data

        if key is None:
            status_code, body = publish()
            replayed = False
        else:
            result = idempotency.execute_idempotently(
                user=request.user,
                key=key,
                fingerprint=idempotency.fingerprint_request(request, serializer.validated_data),
                operation=publish,
            )
            status_code, body, replayed = result.status_code, result.body, result.replayed

        headers = {
            "Location": reverse("post-detail", kwargs={"pk": body["id"]}, request=request),
            "ETag": f'"{body["version"]}"',
        }
        if replayed:
            headers[idempotency.REPLAYED_HEADER] = "true"
        return Response(body, status=status_code, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        post = self.get_object()  # 404 if missing/deleted, 403 if not the author
        expected_version = services.parse_if_match(request)

        serializer = self.get_serializer(post, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            post = services.update_post(
                post=post,
                changes=serializer.validated_data,
                expected_version=expected_version,
            )
        except services.PreconditionFailed as exc:
            return self._precondition_failed(exc.current)
        return self._post_response(post)

    def destroy(self, request, *args, **kwargs):
        # Look up deleted posts too, so the author's retried DELETE can be
        # acknowledged with the same 204 as the original request.
        post = get_object_or_404(Post.all_objects, pk=kwargs["pk"])
        if post.is_deleted:
            if post.author_id == request.user.pk:
                return Response(status=status.HTTP_204_NO_CONTENT)
            raise NotFound("No Post matches the given query.")

        self.check_object_permissions(request, post)  # 403 if not the author
        try:
            services.soft_delete_post(post=post, expected_version=services.parse_if_match(request))
        except services.PreconditionFailed as exc:
            return self._precondition_failed(exc.current)
        return Response(status=status.HTTP_204_NO_CONTENT)
