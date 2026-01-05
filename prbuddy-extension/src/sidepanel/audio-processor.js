/**
 * AudioWorklet Processor for PCM16 recording.
 * This file must be loaded as a separate module due to Chrome extension CSP.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.bufferSize = 4096;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input && input[0]) {
      for (let i = 0; i < input[0].length; i++) {
        this.buffer.push(input[0][i]);
      }

      while (this.buffer.length >= this.bufferSize) {
        const chunk = this.buffer.splice(0, this.bufferSize);
        this.port.postMessage({ audio: new Float32Array(chunk) });
      }
    }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
