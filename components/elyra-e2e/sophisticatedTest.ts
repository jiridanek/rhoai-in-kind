// fromHere.tester.test.ts
import pluginTester from 'babel-plugin-tester';
import fromHerePlugin from './fromHere'; // Adjust path

pluginTester({
    plugin: fromHerePlugin,
    pluginName: 'transform-from-here', // Optional: For better error messages
    // Prevent global configs from interfering
    babelOptions: {
        configFile: false,
        babelrc: false,
    },
    // Use 'tests' object for inline code or file paths
    tests: {
        'removes code before and keeps used variables': {
            // Use 'code' for input, 'output' for expected output
            code: `
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
      `,
            // babel-plugin-tester often uses prettier internally for comparison,
            // making it less sensitive to minor whitespace differences.
            output: `
        function processData(inputParam, threshold) {
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
        }
      `,
        },

        'no change if marker is absent': `
      function simple(a) {
        const b = a + 1;
        console.log(b);
        return b;
      }
    `, // If output is same as input, just provide code

        'throws on multiple markers': {
            code: `
        function multiple(a) {
          fromHere();
          console.log(a);
          fromHere();
          return a;
        }
      `,
            // Use 'error' to assert that the plugin throws
            error: /Multiple fromHere\(\) calls found/, // Can be boolean, string, regex, or error constructor
        },

        // You can also use fixtures:
        // 'basic fixture test': {
        //   fixture: 'path/to/input.js',
        //   outputFixture: 'path/to/expected_output.js',
        // }
    },
});