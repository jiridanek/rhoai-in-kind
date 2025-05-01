// example-from-here.js

// Placeholder for Babel analysis - doesn't exist at runtime
function fromHere() { /* Babel removes this */ }

function processData(inputParam, threshold) {
    const intermediateResult = inputParam * 2; // Should be kept (used by processFurther)
    const unusedData = { value: 100 }; // Should be removed
    let counter = 0; // Should be removed
    const configValue = threshold + 5; // Should be kept (used below)

    function helperUtil() { // Should be removed (not used after fromHere)
        console.log("Helper");
    }

    function processFurther(data) { // Should be kept (used below)
        return data / configValue; // Uses configValue
    }

    console.log("Initial processing done."); // Should be removed

    fromHere(); // The marker

    console.log("Starting final processing."); // Keep
    const finalResult = processFurther(intermediateResult); // Keep (uses processFurther, intermediateResult)
    console.log(`Final result based on threshold ${configValue}:`, finalResult); // Keep (uses configValue)
    console.log("Input param was:", inputParam); // Keep (uses inputParam)

    // counter++; // This would cause an error if counter declaration was removed

    return finalResult > 1;
}

console.log("Result 1:", processData(10, 5)); // Expect true (20 / 10 = 2)
console.log("---");
console.log("Result 2:", processData(3, 5));  // Expect false (6 / 10 = 0.6)

    

// npx babel example-from-here.js --out-file example-from-here.transformed.js
// node example-from-here.transformed.js

/**

 */