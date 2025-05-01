// fromHere.test.ts
import { transformSync, TransformOptions } from '@babel/core';
import { describe, it, expect } from '@jest/globals'; // Or from 'vitest'
import fromHerePlugin from './fromHere'; // Adjust path to your plugin file

// Define the options for Babel transformation to ensure consistency
const babelOptions: TransformOptions = {
    plugins: [fromHerePlugin],
    // Prevent other babel configs (like babel.config.js) from interfering
    configFile: false,
    babelrc: false,
};

// Helper function with explicit types
const transformCode = (inputCode: string): string | null => {
    const result = transformSync(inputCode, babelOptions);
    // Return transformed code, or null if transformation fails unexpectedly
    return result?.code ?? null;
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

        const transformedCode = transformCode(input);

        // Using Jest snapshots is highly recommended for comparing code blocks
        // It handles formatting differences gracefully.
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
        const transformedCode = transformCode(input);
        // Expect the snapshot to match the original (or slightly formatted) code
        expect(transformedCode).toMatchSnapshot();
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
        // Expect the transform function to throw an error matching the regex
        expect(() => transformCode(input)).toThrow(
            /Multiple fromHere\(\) calls found/
        );
    });

    // Consider adding more specific test cases for edge scenarios:
    // - Functions without block statements
    // - Class declarations and usage
    // - Destructuring patterns (`const { x } = ...`, `const [y] = ...`)
    // - `var` declarations (if supported by the plugin)
});