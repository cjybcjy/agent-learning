"""Export FinBERT to ONNX with INT8 dynamic quantization.

Usage:
    pip install optimum[onnxruntime] torch
    python scripts/export_onnx.py --model ProsusAI/finbert --output models/finbert_en
    python scripts/export_onnx.py --model yiyanghkust/finbert-tone --output models/finbert_zh

This script:
1. Downloads the HuggingFace model
2. Exports to ONNX format via optimum
3. Applies INT8 dynamic quantization to reduce size and improve CPU throughput
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FinBERT to quantized ONNX")
    parser.add_argument("--model", default="ProsusAI/finbert", help="HuggingFace model ID")
    parser.add_argument("--output", default="models/finbert_en", help="Output directory")
    args = parser.parse_args()

    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
    except ImportError as e:
        raise SystemExit(
            "Missing dependencies. Install: pip install optimum[onnxruntime] torch"
        ) from e

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] Loading model: {args.model}")
    model = ORTModelForSequenceClassification.from_pretrained(args.model, export=True)
    model.save_pretrained(output_dir)

    print(f"[2/3] Applying INT8 dynamic quantization...")
    quantizer = ORTQuantizer.from_pretrained(output_dir)
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False)
    quantizer.quantize(save_dir=output_dir / "quantized", quantization_config=qconfig)

    print(f"[3/3] Saving tokenizer...")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tokenizer.save_pretrained(output_dir)

    print(f"Done! Model exported to: {output_dir}")
    print(f"Quantized model at: {output_dir / 'quantized'}")


if __name__ == "__main__":
    main()
