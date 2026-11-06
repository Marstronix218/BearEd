Speaker x-vectors for SpeechT5 TTS, extracted from the
[Matthijs/cmu-arctic-xvectors](https://huggingface.co/datasets/Matthijs/cmu-arctic-xvectors)
dataset (CMU ARCTIC speakers). Stored here because recent `datasets`
releases can no longer load that script-based dataset.

- `female.npy` — speaker `slt` (US English, female), utterance #7306
- `male.npy` — speaker `bdl` (US English, male), mean of all 1133 utterances,
  rescaled to the norm of a single x-vector

Add a voice by saving a 512-d float32 x-vector as `voices/<name>.npy`;
it then appears as `--voice <name>`.
