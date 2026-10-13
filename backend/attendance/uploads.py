"""Bounded in-memory uploads: biometric plaintext must never spool to a public temp directory."""
import io
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler
from django.core.files.uploadedfile import InMemoryUploadedFile

class PrivateMemoryUploadHandler(FileUploadHandler):
    chunk_size = 64 * 1024
    total_limit = 20 * 1024 * 1024
    file_limit = 5 * 1024 * 1024
    def __init__(self, request=None):
        super().__init__(request)
        self.total = 0
    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length and content_length > self.total_limit:
            raise RequestDataTooBig('Upload exceeds 20 MB request limit.')
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file = io.BytesIO()
        self.current = 0
    def receive_data_chunk(self, raw_data, start):
        self.total += len(raw_data)
        self.current += len(raw_data)
        if self.total > self.total_limit or self.current > self.file_limit:
            self.file.close()
            raise RequestDataTooBig('Upload exceeds bounded private-memory limit.')
        self.file.write(raw_data)
    def file_complete(self, file_size):
        self.file.seek(0)
        return InMemoryUploadedFile(self.file, self.field_name, self.file_name, self.content_type, file_size, self.charset)
