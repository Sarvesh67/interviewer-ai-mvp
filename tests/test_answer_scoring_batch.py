"""
Tests for batch answer scoring optimisation.

Compares score_all_answers (old: N LLM calls) with
score_all_answers_batch (new: 1 LLM call per chunk of 10).

All Gemini calls are mocked — no API key required.
"""

import json
import types
import pytest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS = [
    {
        "question": "Explain REST vs GraphQL",
        "expected_competencies": ["API design", "trade-offs"],
        "scoring_rubric": {"9-10": "deep comparison", "5-8": "basic comparison"},
        "good_answer_example": "REST uses resource-based URLs while GraphQL uses a single endpoint...",
        "red_flags": ["confuses REST with SOAP"],
    },
    {
        "question": "What is a database index?",
        "expected_competencies": ["databases", "performance"],
        "scoring_rubric": {"9-10": "explains B-tree", "5-8": "knows it speeds queries"},
        "good_answer_example": "An index is a data structure that improves query speed...",
        "red_flags": ["says indexes always help"],
    },
    {
        "question": "Describe the event loop in Node.js",
        "expected_competencies": ["async programming", "Node internals"],
        "scoring_rubric": {"9-10": "mentions libuv and phases", "5-8": "basic understanding"},
        "good_answer_example": "The event loop processes callbacks in phases...",
        "red_flags": ["says Node is multi-threaded"],
    },
]

SAMPLE_ANSWERS = [
    {
        "question_idx": 0,
        "transcript": "REST uses URLs for resources, GraphQL has one endpoint with queries.",
        "conversation": [
            {"role": "interviewer", "text": "Explain REST vs GraphQL", "type": "question"},
            {"role": "candidate", "text": "REST uses URLs for resources, GraphQL has one endpoint with queries.", "type": "answer"},
        ],
    },
    {
        "question_idx": 1,
        "transcript": "An index makes queries faster by avoiding full table scans.",
        "conversation": [
            {"role": "interviewer", "text": "What is a database index?", "type": "question"},
            {"role": "candidate", "text": "An index makes queries faster by avoiding full table scans.", "type": "answer"},
        ],
    },
    {
        "question_idx": 2,
        "transcript": "The event loop handles async operations using a callback queue.",
        "conversation": [
            {"role": "interviewer", "text": "Describe the event loop in Node.js", "type": "question"},
            {"role": "candidate", "text": "The event loop handles async operations using a callback queue.", "type": "answer"},
        ],
    },
]


def _make_score(idx, score=7):
    """Helper: build a valid score dict matching the expected schema."""
    return {
        "score": score,
        "reasoning": f"Answer {idx} showed adequate understanding.",
        "strengths": ["Clear communication"],
        "weaknesses": ["Could go deeper"],
        "depth_level": "intermediate",
        "communication_clarity": "good",
        "technical_accuracy": "partial",
        "follow_up_recommended": False,
        "follow_up_question": "",
    }


def _make_gemini_response(text):
    """Create a mock Gemini response object with .text and .candidates."""
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    resp = MagicMock()
    resp.text = text
    resp.candidates = [candidate]
    return resp


# ---------------------------------------------------------------------------
# Patch helpers — avoids repeating the same monkeypatch block everywhere
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings(monkeypatch):
    """Patch settings so no .env is needed."""
    import config
    monkeypatch.setattr(config.settings, "GEMINI_API_KEY", "test-key-fake")
    monkeypatch.setattr(config.settings, "GEMINI_SCORING_MODEL", "gemini-test")


@pytest.fixture
def mock_genai():
    """Patch google.generativeai used inside answer_scoring."""
    with patch("core.answer_scoring.genai") as mock:
        yield mock


# ===========================================================================
# 1. OLD path — score_all_answers (N individual calls)
# ===========================================================================

class TestScoreAllAnswersOld:
    """Verify the original N-call path."""

    def test_makes_n_calls(self, mock_settings, mock_genai):
        """score_all_answers makes one generate_content call per answer."""
        from core.answer_scoring import score_all_answers

        single_score = json.dumps(_make_score(0))
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(single_score)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        assert len(scores) == 3
        assert mock_model.generate_content.call_count == 3, (
            f"Old path should make 3 LLM calls, made {mock_model.generate_content.call_count}"
        )

    def test_skipped_no_llm_call(self, mock_settings, mock_genai):
        """Skipped answers must not trigger an LLM call."""
        from core.answer_scoring import score_all_answers

        answers = [
            {"question_idx": 0, "transcript": "", "skipped": True, "conversation": []},
            {"question_idx": 1, "transcript": "some answer", "conversation": []},
        ]
        single_score = json.dumps(_make_score(0))
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(single_score)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers(answers, SAMPLE_QUESTIONS)

        assert len(scores) == 2
        assert scores[0]["skipped"] is True
        assert scores[0]["score"] == 0
        # Only 1 LLM call for the non-skipped answer
        assert mock_model.generate_content.call_count == 1

    def test_output_schema(self, mock_settings, mock_genai):
        """Each score dict has all required fields."""
        from core.answer_scoring import score_all_answers

        single_score = json.dumps(_make_score(0))
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(single_score)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers(SAMPLE_ANSWERS[:1], SAMPLE_QUESTIONS)
        s = scores[0]

        required_keys = {
            "score", "reasoning", "strengths", "weaknesses",
            "depth_level", "communication_clarity", "technical_accuracy",
            "follow_up_recommended", "question_idx", "question",
        }
        assert required_keys.issubset(s.keys()), f"Missing keys: {required_keys - s.keys()}"


# ===========================================================================
# 2. NEW path — score_all_answers_batch (1 call per chunk)
# ===========================================================================

class TestScoreAllAnswersBatch:
    """Verify the batched single-call path."""

    def test_makes_one_call(self, mock_settings, mock_genai):
        """score_all_answers_batch makes exactly 1 generate_content call for <= 10 answers."""
        from core.answer_scoring import score_all_answers_batch

        batch_response = json.dumps([_make_score(i) for i in range(3)])
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        assert len(scores) == 3
        assert mock_model.generate_content.call_count == 1, (
            f"Batch path should make 1 LLM call, made {mock_model.generate_content.call_count}"
        )

    def test_skipped_no_llm_call(self, mock_settings, mock_genai):
        """Skipped answers are handled locally, non-skipped go through the batch call."""
        from core.answer_scoring import score_all_answers_batch

        answers = [
            {"question_idx": 0, "transcript": "", "skipped": True, "conversation": []},
            {"question_idx": 1, "transcript": "some answer", "conversation": []},
        ]
        batch_response = json.dumps([_make_score(0)])
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(answers, SAMPLE_QUESTIONS)

        assert len(scores) == 2
        assert scores[0]["skipped"] is True
        assert scores[0]["score"] == 0
        # 1 LLM call for the single non-skipped answer
        assert mock_model.generate_content.call_count == 1

    def test_all_skipped_no_llm_call(self, mock_settings, mock_genai):
        """If every answer is skipped, zero LLM calls should be made."""
        from core.answer_scoring import score_all_answers_batch

        answers = [
            {"question_idx": 0, "transcript": "", "skipped": True, "conversation": []},
            {"question_idx": 1, "transcript": "", "skipped": True, "conversation": []},
        ]
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(answers, SAMPLE_QUESTIONS)

        assert len(scores) == 2
        assert all(s["skipped"] for s in scores)
        assert mock_model.generate_content.call_count == 0

    def test_output_schema_matches_old(self, mock_settings, mock_genai):
        """Batch output should contain the same fields as individual scoring."""
        from core.answer_scoring import score_all_answers_batch

        batch_response = json.dumps([_make_score(i) for i in range(3)])
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        required_keys = {
            "score", "reasoning", "strengths", "weaknesses",
            "depth_level", "communication_clarity", "technical_accuracy",
            "follow_up_recommended", "question_idx", "question",
        }
        for s in scores:
            assert required_keys.issubset(s.keys()), f"Missing keys: {required_keys - s.keys()}"

    def test_score_clamped_to_range(self, mock_settings, mock_genai):
        """Scores outside 0-10 should be clamped."""
        from core.answer_scoring import score_all_answers_batch

        bad_scores = [_make_score(0, score=15), _make_score(1, score=-3), _make_score(2, score=7)]
        batch_response = json.dumps(bad_scores)
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        assert scores[0]["score"] == 10  # clamped from 15
        assert scores[1]["score"] == 0   # clamped from -3
        assert scores[2]["score"] == 7   # untouched

    def test_uses_json_mode(self, mock_settings, mock_genai):
        """The generation_config should include response_mime_type and response_schema."""
        from core.answer_scoring import score_all_answers_batch

        batch_response = json.dumps([_make_score(0)])
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        score_all_answers_batch(SAMPLE_ANSWERS[:1], SAMPLE_QUESTIONS)

        call_kwargs = mock_model.generate_content.call_args
        gen_config = call_kwargs.kwargs.get("generation_config") or call_kwargs[1].get("generation_config")
        assert gen_config["response_mime_type"] == "application/json"
        assert "response_schema" in gen_config
        assert gen_config["response_schema"]["type"] == "array"

    def test_max_output_tokens_scales(self, mock_settings, mock_genai):
        """max_output_tokens should be 400 * N answers in the chunk."""
        from core.answer_scoring import score_all_answers_batch

        batch_response = json.dumps([_make_score(i) for i in range(3)])
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        gen_config = mock_model.generate_content.call_args.kwargs["generation_config"]
        assert gen_config["max_output_tokens"] == 400 * 3

    def test_chunking_over_10(self, mock_settings, mock_genai):
        """Answers beyond chunk size (10) should trigger multiple calls."""
        from core.answer_scoring import score_all_answers_batch

        n = 12
        questions = SAMPLE_QUESTIONS * 4  # 12 questions
        answers = [
            {"question_idx": i, "transcript": f"Answer {i}", "conversation": []}
            for i in range(n)
        ]

        # First chunk (10 answers), second chunk (2 answers)
        resp_chunk1 = json.dumps([_make_score(i) for i in range(10)])
        resp_chunk2 = json.dumps([_make_score(i) for i in range(2)])
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = [
            _make_gemini_response(resp_chunk1),
            _make_gemini_response(resp_chunk2),
        ]
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(answers, questions)

        assert len(scores) == 12
        assert mock_model.generate_content.call_count == 2, (
            f"12 answers should produce 2 batch calls (10+2), got {mock_model.generate_content.call_count}"
        )

    def test_fallback_on_error(self, mock_settings, mock_genai):
        """If the batch call fails, should fall back to individual scoring."""
        from core.answer_scoring import score_all_answers_batch

        single_score = json.dumps(_make_score(0))
        mock_model = MagicMock()
        # Batch call raises, fallback individual calls succeed
        mock_model.generate_content.side_effect = [
            RuntimeError("Simulated batch failure"),
            _make_gemini_response(single_score),
            _make_gemini_response(single_score),
            _make_gemini_response(single_score),
        ]
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        assert len(scores) == 3
        # 1 failed batch + 3 individual fallbacks = 4 calls
        assert mock_model.generate_content.call_count == 4

    def test_wrong_count_triggers_fallback(self, mock_settings, mock_genai):
        """If the batch returns wrong number of scores, should fall back."""
        from core.answer_scoring import score_all_answers_batch

        # Return 2 scores for 3 answers — should trigger fallback
        bad_batch = json.dumps([_make_score(0), _make_score(1)])
        single_score = json.dumps(_make_score(0))
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = [
            _make_gemini_response(bad_batch),
            _make_gemini_response(single_score),
            _make_gemini_response(single_score),
            _make_gemini_response(single_score),
        ]
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        assert len(scores) == 3
        # 1 failed batch + 3 individual fallbacks
        assert mock_model.generate_content.call_count == 4

    def test_question_idx_out_of_range(self, mock_settings, mock_genai):
        """Should raise ValueError for invalid question index."""
        from core.answer_scoring import score_all_answers_batch

        bad_answers = [{"question_idx": 99, "transcript": "answer", "conversation": []}]

        with pytest.raises(ValueError, match="out of range"):
            score_all_answers_batch(bad_answers, SAMPLE_QUESTIONS)

    def test_preserves_order_with_skipped(self, mock_settings, mock_genai):
        """Skipped and non-skipped answers should maintain their original order."""
        from core.answer_scoring import score_all_answers_batch

        answers = [
            {"question_idx": 0, "transcript": "answer 0", "conversation": []},
            {"question_idx": 1, "transcript": "", "skipped": True, "conversation": []},
            {"question_idx": 2, "transcript": "answer 2", "conversation": []},
        ]
        batch_response = json.dumps([_make_score(0, score=8), _make_score(2, score=6)])
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _make_gemini_response(batch_response)
        mock_genai.GenerativeModel.return_value = mock_model

        scores = score_all_answers_batch(answers, SAMPLE_QUESTIONS)

        assert len(scores) == 3
        assert scores[0]["question_idx"] == 0
        assert scores[0]["score"] == 8
        assert scores[1]["question_idx"] == 1
        assert scores[1]["skipped"] is True
        assert scores[1]["score"] == 0
        assert scores[2]["question_idx"] == 2
        assert scores[2]["score"] == 6


# ===========================================================================
# 3. Comparison: old vs new produce equivalent output
# ===========================================================================

class TestOldVsBatchComparison:
    """Side-by-side comparison: both paths should produce equivalent results."""

    def test_same_scores_same_input(self, mock_settings, mock_genai):
        """Given identical mock LLM output, old and new should return identical score lists."""
        from core.answer_scoring import score_all_answers, score_all_answers_batch

        expected_scores = [_make_score(i, score=7 + i) for i in range(3)]

        # --- Old path (3 individual calls) ---
        mock_model_old = MagicMock()
        mock_model_old.generate_content.side_effect = [
            _make_gemini_response(json.dumps(expected_scores[i])) for i in range(3)
        ]
        mock_genai.GenerativeModel.return_value = mock_model_old
        old_scores = score_all_answers(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        # --- New path (1 batch call) ---
        mock_model_new = MagicMock()
        mock_model_new.generate_content.return_value = _make_gemini_response(
            json.dumps(expected_scores)
        )
        mock_genai.GenerativeModel.return_value = mock_model_new
        new_scores = score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)

        # Compare
        assert len(old_scores) == len(new_scores) == 3
        for old, new in zip(old_scores, new_scores):
            assert old["score"] == new["score"]
            assert old["reasoning"] == new["reasoning"]
            assert old["strengths"] == new["strengths"]
            assert old["weaknesses"] == new["weaknesses"]
            assert old["depth_level"] == new["depth_level"]
            assert old["communication_clarity"] == new["communication_clarity"]
            assert old["technical_accuracy"] == new["technical_accuracy"]
            assert old["question_idx"] == new["question_idx"]
            assert old["question"] == new["question"]

    def test_call_count_comparison(self, mock_settings, mock_genai):
        """Old makes N calls, new makes 1 — verify the optimization."""
        from core.answer_scoring import score_all_answers, score_all_answers_batch

        single_score = json.dumps(_make_score(0))
        batch_scores = json.dumps([_make_score(i) for i in range(3)])

        # Old path
        mock_model_old = MagicMock()
        mock_model_old.generate_content.return_value = _make_gemini_response(single_score)
        mock_genai.GenerativeModel.return_value = mock_model_old
        score_all_answers(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)
        old_calls = mock_model_old.generate_content.call_count

        # New path
        mock_model_new = MagicMock()
        mock_model_new.generate_content.return_value = _make_gemini_response(batch_scores)
        mock_genai.GenerativeModel.return_value = mock_model_new
        score_all_answers_batch(SAMPLE_ANSWERS, SAMPLE_QUESTIONS)
        new_calls = mock_model_new.generate_content.call_count

        assert old_calls == 3, f"Old path: expected 3 calls, got {old_calls}"
        assert new_calls == 1, f"New path: expected 1 call, got {new_calls}"
        print(f"\n  LLM calls — old: {old_calls}, new: {new_calls} (saved {old_calls - new_calls} calls)")

    def test_skipped_handling_identical(self, mock_settings, mock_genai):
        """Both paths should produce the same skipped-answer dict."""
        from core.answer_scoring import score_all_answers, score_all_answers_batch

        answers = [{"question_idx": 0, "transcript": "", "skipped": True, "conversation": []}]
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        old_scores = score_all_answers(answers, SAMPLE_QUESTIONS)
        new_scores = score_all_answers_batch(answers, SAMPLE_QUESTIONS)

        # Both should return score 0 with skipped=True, no LLM calls
        assert old_scores[0]["score"] == new_scores[0]["score"] == 0
        assert old_scores[0]["skipped"] is True
        assert new_scores[0]["skipped"] is True
        assert mock_model.generate_content.call_count == 0
