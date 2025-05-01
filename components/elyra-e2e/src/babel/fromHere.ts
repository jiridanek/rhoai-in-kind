import * as t from '@babel/types';
import { generate } from '@babel/generator';
import traverse, { NodePath, Visitor, Scope, Binding } from '@babel/traverse';

export function fromHere() {
    if (process.env.CI) {
        throw "Using fromHere in committed code in CI is a mistake.";
    }
}

// Helper to check if a node is the fromHere() call statement
// function isFromHereStatement(node: t.Node): node is t.ExpressionStatement {
//     return (
//         t.isExpressionStatement(node) &&
//         t.isCallExpression(node.expression) &&
//         t.isIdentifier(node.expression.callee, { name: 'fromHere' }) &&
//         node.expression.arguments.length === 0
//     );
// }

function isFromHereStatement(path: NodePath<t.Node>): path is NodePath<t.ExpressionStatement> {
    // Must be an ExpressionStatement
    if (!path.isExpressionStatement()) {
        return false;
    }

    let callExprPath: NodePath<t.CallExpression> | null = null;
    const expressionPath = path.get('expression');

    // Case 1: Direct CallExpression, e.g., fromHere()
    if (expressionPath.isCallExpression()) {
        callExprPath = expressionPath;
    }
    // Case 2: Sequence Expression, e.g., (0, _fromHere.fromHere)() // this may be a mistake
    else if (expressionPath.isSequenceExpression()) {
        const expressions = expressionPath.get('expressions');
        const lastExpression = expressions[expressions.length - 1];
        if (lastExpression?.isCallExpression()) {
            callExprPath = lastExpression;
        }
    }

    // If we didn't find a CallExpression in the expected places, bail out
    if (!callExprPath) {
        return false;
    }

    // Check argument count first (simple check)
    if (callExprPath.node.arguments.length !== 0) {
        return false;
    }

    let calleePath = callExprPath.get('callee');
    if (calleePath.isSequenceExpression()) {
        const expressions = calleePath.get('expressions');
        const lastExpression = expressions[expressions.length - 1];
        if (lastExpression?.isCallExpression() || lastExpression?.isMemberExpression()) {
            calleePath = lastExpression;
        } else {
            throw new Error(`Unexpected lastExpression type ${lastExpression.node.type}`);
        }
    }
    let binding: Binding | undefined | null = null;
    let potentialCalleeName: string | null = null;

    // --- Identify the binding based on callee type ---

    // Case A: Callee is a direct Identifier, e.g., fromHere()
    if (calleePath.isIdentifier()) {
        potentialCalleeName = calleePath.node.name;
        binding = calleePath.scope.getBinding(potentialCalleeName);
    }
    // Case B: Callee is a MemberExpression, e.g., _fromHere.fromHere
    else if (calleePath.isMemberExpression() && !calleePath.node.computed && t.isIdentifier(calleePath.node.property)) {
        const objectPath = calleePath.get('object');
        const propertyName = calleePath.node.property.name;

        // We expect the property to be 'fromHere'
        if (propertyName === 'fromHere' && objectPath.isIdentifier()) {
            potentialCalleeName = propertyName
            // Get the binding for the object part (_fromHere)
            let objectNodeName = objectPath.node.name; // The name of the imported object/namespace
            binding = objectPath.scope.getBinding(objectNodeName);
        }
    }

    // simple case of fromHere() used directly
    if (!binding && potentialCalleeName === "fromHere") {
        return true;
    }

    // we're dealing with a defined function
    if (binding && binding.path.isFunction() && potentialCalleeName === "fromHere") {
        return true;
    }

    if (binding && binding.path.isVariableDeclarator() && potentialCalleeName === "fromHere") {
        return true;
    }

    // --- Validate the binding ---
    if (
        !binding ||
        binding.kind !== 'module' || // Ensure it's an import binding
        !binding.path.parentPath?.isImportDeclaration() || // Check parent is ImportDeclaration
        !binding.path.parentPath.node.source.value.endsWith('fromHere') // Check the source module path
    ) {
        // If the binding doesn't match the import, it's not our function
        return false;
    }

    // Additionally, ensure the specific import specifier matches 'fromHere'
    // This handles cases like `import * as fh from './fromHere'` where the binding is correct
    // but the original imported name might differ.
    if (binding.path.isImportSpecifier() && binding.path.node.imported.type === 'Identifier' && binding.path.node.imported.name !== 'fromHere') {
        return false; // Imported name doesn't match
    }
    // Could add checks for ImportDefaultSpecifier or ImportNamespaceSpecifier if needed

    // If all checks pass, it's the function we're looking for
    return true;
}

// Define the structure for the Babel plugin export
interface PluginDefinition {
    name: string;
    visitor: Visitor;
}

export default function ({ types }: { types: typeof t }): PluginDefinition {
    return {
        name: 'transform-from-here',
        visitor: {
            Function(path: NodePath<t.Function>) {
                // console.log(`[fromHere plugin] Visiting Function type: ${path.node.type}, ${path.node.id?.name ?? 'anonymous'} async: ${path.node.async}`);

                // if (path.node.id?.name === "bafff") {
                //     console.log("in the bafff");
                // }
                const functionBodyPath = path.get('body');

                // Ensure we are working with a function that has a BlockStatement body
                if (!functionBodyPath.isBlockStatement()) {
                    const functionName = (t.isFunctionDeclaration(path.node) || t.isFunctionExpression(path.node))
                        ? path.node.id?.name
                        : null;
                    // console.warn(`Skipping function '${functionName ?? 'anonymous'}' as it does not have a block statement body.`);
                    return;
                }

                const bodyPaths: NodePath<t.Statement>[] = functionBodyPath.get('body');
                let fromHereIndex: number = -1;
                let fromHerePath: NodePath<t.Statement> | null = null;

                // --- Step 1: Find the fromHere() marker ---
                for (let i = 0; i < bodyPaths.length; i++) {
                    const currentPath = bodyPaths[i];
                    if (isFromHereStatement(currentPath)) {
                        if (fromHereIndex !== -1) {
                            throw currentPath.buildCodeFrameError(
                                'Multiple fromHere() calls found in the same function scope. Only one is allowed.'
                            );
                        }
                        fromHereIndex = i;
                        fromHerePath = currentPath;
                    }
                }

                // If no marker found, exit
                if (fromHereIndex === -1 || !fromHerePath) {
                    return;
                }

                console.log("aaaaaaa")


                // --- Step 2: Split statements ---
                const beforeStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(0, fromHereIndex);
                const beforeStatementNodes = new Set(beforeStatementsPaths.map(p => p.node));
                // *** CHANGE HERE: Include the marker statement itself ***
                const afterStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(fromHereIndex); // Changed from fromHereIndex + 1

                // --- Step 3: Analyze variable usage AFTER fromHere() ---
                // We need to exclude the marker itself from usage analysis,
                // otherwise 'fromHere' might be incorrectly marked as used if declared before.
                const afterStatementsBlock: t.BlockStatement = t.blockStatement(
                    // Map nodes starting from *after* the marker for analysis
                    afterStatementsPaths.slice(1).map(p => p.node)
                );
                const usedVariableNames = new Set<string>();

                traverse(afterStatementsBlock, {
                    Identifier(identifierPath: NodePath<t.Identifier>) {
                        if (!identifierPath.isReferencedIdentifier()) {
                            return;
                        }
                        // Exclude the 'fromHere' identifier in the marker call itself
                        if (identifierPath.node.name === 'fromHere' &&
                            identifierPath.parentPath.isCallExpression() &&
                            identifierPath.parentPath.parentPath === fromHerePath) {
                            return;
                        }

                        const identifierName = identifierPath.node.name;
                        const binding = path.scope.getBinding(identifierName);
                        if (binding && binding.scope === path.scope) {
                            let declarationStatementPath: NodePath | null = binding.path;
                            while (declarationStatementPath && !declarationStatementPath.isStatement()) {
                                declarationStatementPath = declarationStatementPath.parentPath;
                            }
                            if (declarationStatementPath && beforeStatementNodes.has(declarationStatementPath.node)) {
                                usedVariableNames.add(identifierName);
                            }
                        }
                    },
                    CallExpression(callPath: NodePath<t.CallExpression>) {
                        const callee = callPath.node.callee;
                        if (t.isIdentifier(callee) && callPath.get('callee').isReferencedIdentifier()) {
                            const calleeName = callee.name;
                            const binding = path.scope.getBinding(calleeName);
                            if (binding && binding.path.isFunctionDeclaration() && binding.scope === path.scope) {
                                const declarationStatementPath = binding.path;
                                if (beforeStatementNodes.has(declarationStatementPath.node)) {
                                    usedVariableNames.add(calleeName);
                                }
                            }
                        }
                    }
                }, path.scope, {}, functionBodyPath);


                // --- Step 4: Identify necessary declarations BEFORE fromHere() ---
                const necessaryDeclarationNodes: t.Statement[] = [];
                const addedDeclarations = new Set<t.Node>();

                beforeStatementsPaths.forEach(statementPath => {
                    let declarationNodeToAdd: t.Statement | null = null;

                    if (statementPath.isVariableDeclaration()) {
                        const necessaryDeclarators: t.VariableDeclarator[] = [];
                        statementPath.node.declarations.forEach(declarator => {
                            const identifiersMap = t.getBindingIdentifiers(declarator.id);
                            let declaratorNeeded = false;
                            Object.values(identifiersMap).flat().forEach((node: t.Node | null) => {
                                if (node && t.isIdentifier(node) && usedVariableNames.has(node.name)) {
                                    declaratorNeeded = true;
                                }
                            });
                            if (declaratorNeeded && !necessaryDeclarators.includes(declarator)) {
                                necessaryDeclarators.push(declarator);
                            }
                        });
                        if (necessaryDeclarators.length > 0) {
                            declarationNodeToAdd = t.variableDeclaration(
                                statementPath.node.kind,
                                necessaryDeclarators
                            );
                        }
                    }
                    else if (statementPath.isFunctionDeclaration()) {
                        if (statementPath.node.id && usedVariableNames.has(statementPath.node.id.name)) {
                            declarationNodeToAdd = statementPath.node;
                        }
                    }
                    // Add similar check for ClassDeclaration if needed
                    // else if (statementPath.isClassDeclaration()) { ... }

                    if (declarationNodeToAdd) {
                        if (!addedDeclarations.has(declarationNodeToAdd)) {
                            necessaryDeclarationNodes.push(declarationNodeToAdd);
                            addedDeclarations.add(declarationNodeToAdd);
                        }
                    }
                });

                // --- Step 5: Construct the new function body ---
                // afterStatementsPaths now includes the marker, so this combines correctly
                const newBodyStatements: t.Statement[] = [
                    ...necessaryDeclarationNodes,
                    ...afterStatementsPaths.map(p => p.node)
                ];

                // add empty statements to the shortened function to match the original line count
                // because intellij runs playwright tests by specifying the test function's line number
                let newBody = t.blockStatement(newBodyStatements)
                let code = generate(newBody).code;
                let loc = (code?.match(/\n/g) || []).length + 1;
                const bodyNode = functionBodyPath.node;
                if (!bodyNode.loc) {
                    throw new Error('Function body does not have a location.');
                }
                const originalLineCount = bodyNode.loc.end.line - bodyNode.loc.start.line + 1;
                const diff = originalLineCount - loc;
                if (diff < 0) {
                    throw new Error(`Function body has ${loc} lines, but the original had ${originalLineCount}. Das ist nicht moglich!`);
                }
                for (let i = 0; i < diff; i++) {
                    newBodyStatements.push(t.emptyStatement());
                }

                // --- Step 6: Replace the body ---
                functionBodyPath.replaceWith(t.blockStatement(newBodyStatements));
            },
        },
    };
}
