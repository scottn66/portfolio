function patches = samplePatches(rawImages, patchSize, numPatches)
% rawImages is of size (image width)*(image height) by number_of_images
% Here we assume that image width = image height
imWidth = sqrt(size(rawImages,1));
imHeight = imWidth;
numImages = size(rawImages,2);
rawImages = reshape(rawImages,imWidth,imHeight,numImages); 


% Initialize patches with zeros.  Your code will fill in this matrix--one
% column per patch 
patches = zeros(patchSize*patchSize, numPatches);

maxWidth = imWidth - patchSize + 1;
maxHeight = imHeight - patchSize + 1;

% startRow = randi(maxHeight,numPatches,1);
% startCol = randi(maxWidth,numPatches,1);
% imageNums = randi(numImages,numPatches,1); 
% full_patches = rawImages(startRow:startRow+patchSize-1,...
%     startCol:startCol+patchSize-1, imageNums);

for num = 1:numPatches
    x = randi(maxHeight);
    y = randi(maxWidth);
    img = randi(numImages);
    p = rawImages(x:x+patchSize-1,y:y+patchSize-1, img);
    patches(:,num) = p(:);
end
    

