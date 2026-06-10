import { Jimp } from 'jimp';

const img = await Jimp.read('bull.png');
const { width, height, data } = img.bitmap;
for (let i = 0; i < data.length; i += 4) {
  const r = data[i];
  const g = data[i + 1];
  const b = data[i + 2];
  if (r < 60 && g < 60 && b < 60) {
    data[i + 3] = 0;
  }
}
await img.write('bull.png');
console.log('Done — bull.png is now transparent');
