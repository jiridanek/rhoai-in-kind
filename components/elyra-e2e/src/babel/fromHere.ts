import * as t from '@babel/types';
import traverse, { NodePath, Visitor, Scope, Binding } from '@babel/traverse';

// Helper to check if a node is the fromHere() call statement
// Uses a type predicate to narrow down the type in calling scopes
function isFromHereStatement(node: t.Node): node is t.ExpressionStatement {
    return (
        t.isExpressionStatement(node) &&
        t.isCallExpression(node.expression) &&
        t.isIdentifier(node.expression.callee, { name: 'fromHere' }) &&
        node.expression.arguments.length === 0
    );
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
                const functionBodyPath = path.get('body');

                // Ensure we are working with a function that has a BlockStatement body
                if (!functionBodyPath.isBlockStatement()) {
                    // Check if the node is a type that can have an 'id' before accessing it
                    const functionName = (t.isFunctionDeclaration(path.node) || t.isFunctionExpression(path.node))
                        ? path.node.id?.name // Access id only if it's FunctionDeclaration or FunctionExpression
                        : null; // Arrow functions don't have an id

                    console.warn(`Skipping function '${functionName ?? 'anonymous'}' as it does not have a block statement body.`);
                    return;
                }

                const bodyPaths: NodePath<t.Statement>[] = functionBodyPath.get('body');
                let fromHereIndex: number = -1;
                let fromHerePath: NodePath<t.Statement> | null = null;

                // --- Step 1: Find the fromHere() marker ---
                for (let i = 0; i < bodyPaths.length; i++) {
                    const currentPath = bodyPaths[i];
                    if (isFromHereStatement(currentPath.node)) {
                        if (fromHereIndex !== -1) {
                            // Throw an error if multiple markers are found
                            throw currentPath.buildCodeFrameError(
                                'Multiple fromHere() calls found in the same function scope. Only one is allowed.'
                            );
                        }
                        fromHereIndex = i;
                        fromHerePath = currentPath; // Store the path
                    }
                }

                // If no marker found, exit processing for this function
                if (fromHereIndex === -1 || !fromHerePath) {
                    return;
                }

                // --- Step 2: Split statements ---
                const beforeStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(0, fromHereIndex);
                // Create a Set of the actual nodes for faster/more reliable lookup
                const beforeStatementNodes = new Set(beforeStatementsPaths.map(p => p.node));
                const afterStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(fromHereIndex + 1);

                // --- Step 3: Analyze variable usage AFTER fromHere() ---
                const usedVariableNames = new Set<string>();
                const afterStatementsBlock: t.BlockStatement = t.blockStatement(
                    afterStatementsPaths.map(p => p.node)
                );

                traverse(afterStatementsBlock, {
                    Identifier(identifierPath: NodePath<t.Identifier>) {
                        if (!identifierPath.isReferencedIdentifier()) {
                            return;
                        }

                        const identifierName = identifierPath.node.name;
                        const binding = path.scope.getBinding(identifierName);

                        if (binding && binding.scope === path.scope) {
                            let declarationStatementPath: NodePath | null = binding.path;
                            while (declarationStatementPath && !declarationStatementPath.isStatement()) {
                                declarationStatementPath = declarationStatementPath.parentPath;
                            }

                            // --- Add Detailed Logging ---
                            if (identifierName === 'intermediateResult' || identifierName === 'configValue') {
                                console.log(`[DEBUG] Checking identifier: ${identifierName}`);
                                if (declarationStatementPath) {
                                    console.log(`[DEBUG]   Declaration Node Type: ${declarationStatementPath.node.type}`);
                                    const isInBeforeSet = beforeStatementNodes.has(declarationStatementPath.node);
                                    console.log(`[DEBUG]   Is declaration node in beforeStatementNodes? ${isInBeforeSet}`);
                                    if (!isInBeforeSet) {
                                        // If it's not found, let's log the nodes for comparison
                                        console.log('[DEBUG]   Declaration Node:', declarationStatementPath.node);
                                        console.log('[DEBUG]   Nodes in beforeStatementNodes:', Array.from(beforeStatementNodes));
                                    }
                                } else {
                                    console.log('[DEBUG]   Could not find declaration statement path.');
                                }
                            }
                            // --- End Detailed Logging ---

                            if (declarationStatementPath && beforeStatementNodes.has(declarationStatementPath.node)) {
                                usedVariableNames.add(identifierName);
                            }
                        }
                    },
                    // ... CallExpression visitor remains the same ...
                }, path.scope, {}, functionBodyPath);

                // --- Add Logging for the final set ---
                console.log('[DEBUG] Final usedVariableNames:', Array.from(usedVariableNames));
                // --- End Logging ---

                // --- Step 4: Identify necessary declarations BEFORE fromHere() ---
                const necessaryDeclarationNodes: t.Statement[] = [];
                const addedDeclarations = new Set<t.Node>(); // Prevent adding the same statement node multiple times

                console.log('[DEBUG Step 4] Starting. usedVariableNames:', Array.from(usedVariableNames)); // Log at start

                beforeStatementsPaths.forEach(statementPath => {
                    let declarationNodeToAdd: t.Statement | null = null;

                    // Check for Variable Declarations (const, let, var)
                    if (statementPath.isVariableDeclaration()) {
                        console.log(`[DEBUG Step 4] Processing VariableDeclaration: ${statementPath.node.declarations.map(d => (d.id as any)?.name ?? '?').join(', ')}`);
                        const necessaryDeclarators: t.VariableDeclarator[] = [];
                        statementPath.node.declarations.forEach(declarator => {
                            console.log(`[DEBUG Step 4]   Declarator ID type: ${declarator.id.type}, Name (if Identifier): ${(declarator.id as any)?.name}`);
                            const identifiersMap = t.getBindingIdentifiers(declarator.id);
                            let declaratorNeeded = false;

                            // *** CORRECTED LOOP ***
                            // Iterate directly over all binding nodes returned by getBindingIdentifiers
                            // This handles simple identifiers, object patterns, array patterns etc.
                            Object.values(identifiersMap).flat().forEach((node: t.Node | null) => {
                                // Check if the node is an Identifier and if it's in our used set
                                if (node && t.isIdentifier(node)) {
                                    const nodeName = node.name;
                                    const isInSet = usedVariableNames.has(nodeName);
                                    console.log(`[DEBUG Step 4]     Checking identifier node.name='${nodeName}'. Is in usedVariableNames? ${isInSet}`);
                                    if (isInSet) {
                                        console.log(`[DEBUG Step 4]     Found used identifier '${nodeName}' in declarator.`);
                                        declaratorNeeded = true;
                                        // Optimization: If one binding in the declarator is needed, we keep the whole thing.
                                        // No need to check other bindings within the *same* declarator.
                                        // We can break the inner forEach early, but it's tricky.
                                        // Setting the flag and checking later is simpler.
                                    }
                                } else if (node) {
                                    console.log(`[DEBUG Step 4]     Node is not an Identifier (type: ${node.type})`);
                                } else {
                                    console.log(`[DEBUG Step 4]     Node is null`);
                                }
                            });
                            // *** END CORRECTED LOOP ***


                            if (declaratorNeeded && !necessaryDeclarators.includes(declarator)) {
                                console.log(`[DEBUG Step 4]   Adding declarator for '${(declarator.id as any)?.name ?? '?'}' to necessaryDeclarators.`);
                                necessaryDeclarators.push(declarator);
                            }
                        });

                        if (necessaryDeclarators.length > 0) {
                            console.log(`[DEBUG Step 4]   Reconstructing VariableDeclaration with ${necessaryDeclarators.length} declarator(s).`);
                            declarationNodeToAdd = t.variableDeclaration(
                                statementPath.node.kind,
                                necessaryDeclarators
                            );
                        } else {
                            console.log(`[DEBUG Step 4]   No necessary declarators found for this VariableDeclaration.`);
                        }
                    }
                    // Check for Function Declarations
                    else if (statementPath.isFunctionDeclaration()) {
                        if (statementPath.node.id && usedVariableNames.has(statementPath.node.id.name)) {
                            console.log(`[DEBUG Step 4] Identified necessary FunctionDeclaration: ${statementPath.node.id.name}`); // Log function
                            declarationNodeToAdd = statementPath.node;
                        }
                    }
                    // Check for Class Declarations (add similar logging if needed)
                    // ...

                    // Add the necessary declaration node if found and not already added
                    if (declarationNodeToAdd) {
                        if (!addedDeclarations.has(declarationNodeToAdd)) {
                            console.log(`[DEBUG Step 4] Adding node of type ${declarationNodeToAdd.type} to necessaryDeclarationNodes.`); // Log adding final node
                            necessaryDeclarationNodes.push(declarationNodeToAdd);
                            addedDeclarations.add(declarationNodeToAdd);
                        } else {
                            console.log(`[DEBUG Step 4] Node of type ${declarationNodeToAdd.type} was already added.`); // Log if duplicate
                        }
                    }
                });

                console.log(`[DEBUG Step 4] Finished. necessaryDeclarationNodes count: ${necessaryDeclarationNodes.length}`); // Log final count

                // --- Step 5: Construct the new function body ---
                // Combine the preserved declarations with all statements that came after the marker
                const newBodyStatements: t.Statement[] = [
                    ...necessaryDeclarationNodes,
                    ...afterStatementsPaths.map(p => p.node)
                ];

                // --- Step 6: Replace the body ---
                functionBodyPath.replaceWith(t.blockStatement(newBodyStatements));

                // Optional: Re-crawl the scope if further analysis depends on the modified structure
                // path.scope.crawl();
            },
        },
    };
}