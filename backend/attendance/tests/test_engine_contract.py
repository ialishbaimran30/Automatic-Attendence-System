"""DeepFace adapter contract tests with fake library responses; no real accuracy claims."""
import io
import sys
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
from PIL import Image
from recognition.engine import extract_embedding, RecognitionRejected

class EngineContractTests(TestCase):
    def setUp(self):
        buffer = io.BytesIO()
        Image.new('RGB', (120,120), (120,120,120)).save(buffer, format='JPEG')
        self.data = buffer.getvalue()
        self.vector = np.eye(512)[0].tolist()
        self.cv = SimpleNamespace(IMREAD_COLOR=1, COLOR_BGR2GRAY=2, CV_64F=3,
            imdecode=Mock(return_value=np.ones((120,120,3), dtype='uint8')*120),
            cvtColor=Mock(return_value=np.ones((120,120), dtype='uint8')*120),
            Laplacian=Mock(return_value=np.array([0.,100.])))
        self.face = {'face':np.ones((100,100,3))*.5, 'is_real':True, 'facial_area':{'x':10,'y':10,'w':100,'h':100}}
        self.deep = SimpleNamespace(extract_faces=Mock(return_value=[self.face]), represent=Mock(return_value=[{'embedding':self.vector}]))
    def extract(self):
        with patch.dict(sys.modules, {'cv2':self.cv, 'deepface':SimpleNamespace(DeepFace=self.deep)}):
            return extract_embedding(self.data)
    def test_arcface_only_after_single_face_and_anti_spoofing(self):
        result = self.extract()
        self.assertEqual(result.shape, (512,))
        self.assertTrue(self.deep.extract_faces.call_args.kwargs['anti_spoofing'])
        self.assertTrue(self.deep.extract_faces.call_args.kwargs['enforce_detection'])
        self.assertEqual(self.deep.represent.call_args.kwargs['model_name'], 'ArcFace')
        self.assertEqual(self.deep.represent.call_args.kwargs['normalization'], 'ArcFace')
        self.assertEqual(self.deep.represent.call_args.kwargs['detector_backend'], 'skip')
    def test_reject_multiple_missing_and_failed_liveness_before_representation(self):
        for faces in [[], [self.face,self.face], [{**self.face,'is_real':False}], [{k:v for k,v in self.face.items() if k != 'is_real'}]]:
            with self.subTest(count=len(faces)):
                self.deep.extract_faces.return_value = faces
                with self.assertRaises(RecognitionRejected): self.extract()
                self.deep.represent.assert_not_called()
    def test_dark_and_small_face_quality_rejected(self):
        self.cv.cvtColor.return_value = np.zeros((120,120), dtype='uint8')
        with self.assertRaisesRegex(RecognitionRejected, 'poor_lighting'): self.extract()
        self.deep.represent.assert_not_called()
        self.face['facial_area']['w'] = 30
        with self.assertRaisesRegex(RecognitionRejected, 'face_too_small'): self.extract()
