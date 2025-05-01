// fromHere.test.ts
import { transformSync } from '@babel/core';
import fromHerePlugin from './fromHere'; // Adjust path to your plugin file

// Helper function for cleaner tests (optional)
const transform = (inputCode: string) => {
    const result = transformSync(inputCode, {
        plugins: [fromHerePlugin],
        // Important: Prevent other babel configs (like babel.config.js)
        // from interfering with this specific test transformation.
        configFile: false,
        babelrc: false,
    });
    return result?.code ?? null; // Return transformed code or null
};

describe('babel-plugin-from-here', () => {
    it('should remove code before fromHere() and keep used variables', () => {
        const input = `
              function processData(inputParam, threshold) {
                const intermediateResult = inputParam * 2; // Keep
                const unusedData = { value: 100 }; // Remove
                let counter = 0; // Remove
                const configValue = threshold + 5; // Keep
                function unusedHelper() {} // Remove
                function processFurther(data) { return data / configValue; } // Keep

                console.log("Initial processing done."); // Remove

                fromHere(); // The marker

                console.log("Starting final processing."); // Keep
                const finalResult = processFurther(intermediateResult); // Keep
                console.log(\`Final result based on threshold \${configValue}:\`, finalResult); // Keep
                console.log("Input param was:", inputParam); // Keep
                return finalResult > 1; // Keep
              }
            `;

        // Use backticks for multiline strings and trim indentation for comparison
        // Note: Exact whitespace/formatting might differ slightly based on Babel's output.
        // Consider using a code formatter (like Prettier) on both expected and actual
        // output before comparison, or use snapshot testing.
        const expectedOutput = `function processData(inputParam, threshold) {
  const intermediateResult = inputParam * 2;
  const configValue = threshold + 5;
  function processFurther(data) {
    return data / configValue;
  }
  console.log("Starting final processing.");
  const finalResult = processFurther(intermediateResult);
  console.log(\`Final result based on threshold \${configValue}:\`, finalResult);
  console.log("Input param was:", inputParam);
  return finalResult > 1;
}`;

        const transformedCode = transform(input);

        // Basic comparison (sensitive to whitespace/formatting)
        // expect(transformedCode?.trim()).toBe(expectedOutput.trim());

        // Using Jest snapshots is often easier for comparing code blocks
        expect(transformedCode).toMatchSnapshot();
    });

    it('should do nothing if fromHere() is not present', () => {
        const input = `
              function simple(a) {
                const b = a + 1;
                console.log(b);
                return b;
              }
            `;
        // Use snapshots or compare directly
        expect(transform(input)).toMatchSnapshot();
        // Or compare to input if no transformation is expected (be careful with formatting)
        // expect(transform(input)?.trim()).toBe(input.trim());
    });

    it('should throw an error if multiple fromHere() calls exist', () => {
        const input = `
              function multiple(a) {
                fromHere();
                console.log(a);
                fromHere();
                return a;
              }
            `;
        // Expect the transform function to throw an error
        expect(() => transform(input)).toThrow(/Multiple fromHere\(\) calls found/);
    });

    // Add more tests for edge cases:
    // - Variables declared with var
    // - Class declarations
    // - Destructuring assignments
    // - Empty functions
    // - Functions without block statements (should be skipped)
    // - fromHere() at the very beginning or end
});
