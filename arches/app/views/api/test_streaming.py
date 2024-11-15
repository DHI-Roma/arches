from django.http import StreamingHttpResponse
import time


def test_streaming(request):
    def stream_generator():
        for i in range(1, 11):
            yield f"data: Chunk {i}\n\n"
            time.sleep(1)  # Simulates the delay between chunks

    response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
    response["Cache-Control"] = "no-cache"
    return response
