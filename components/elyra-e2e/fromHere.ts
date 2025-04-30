import * as t from '@babel/types';
import { NodePath, Visitor, Scope } from '@babel/traverse';

// Helper to check if a node is the fromHere() call statement
function isFromHereStatement(node: t.Node): node is t.ExpressionStatement {
    return (
        t.isExpressionStatement(node) &&
        t.isCallExpression(node.expression) &&
        t.isIdentifier(node.expression.callee, { name: 'fromHere' }) &&
        node.expression.arguments.length === 0
    );
}

export default function ({ types }: { types: typeof t }): { name: string; visitor: Visitor } {
    return {
        name: 'transform-from-here',
        visitor: {
            Function(path: NodePath<t.Function>) {
                const functionBodyPath = path.get('body');
                if (!functionBodyPath.isBlockStatement()) {
                    return; // Only process functions with block bodies
                }

                const bodyPaths = functionBodyPath.get('body');
                let fromHereIndex = -1;

                // --- Step 1: Find the fromHere() marker ---
                for (let i = 0; i < bodyPaths.length; i++) {
                    if (isFromHereStatement(bodyPaths[i].node)) {
                        if (fromHereIndex !== -1) {
                            throw bodyPaths[i].buildCodeFrameError(
                                'Multiple fromHere() calls found in the same function scope. Only one is allowed.'
                            );
                        }
                        fromHereIndex = i;
                    }
                }

                // If no marker found, do nothing
                if (fromHereIndex === -1) {
                    return;
                }

                const fromHerePath = bodyPaths[fromHereIndex];

                // --- Step 2: Split statements ---
                const beforeStatementsPaths = bodyPaths.slice(0, fromHereIndex);
                const afterStatementsPaths = bodyPaths.slice(fromHereIndex + 1); // Exclude the fromHere() statement itself

                // --- Step 3: Analyze variable usage AFTER fromHere() ---
                const usedVariableNames = new Set<string>();
                const afterStatementsBlock = t.blockStatement(
                    afterStatementsPaths.map(p => p.node) // Create a temporary block for traversal
                );

                // Traverse the 'after' block to find all referenced identifiers
                // We need a temporary path to traverse correctly
                const tempAfterPath = fromHerePath.parentPath; // Use parent path for context
                if (!tempAfterPath) return; // Should not happen if fromHerePath is valid

                tempAfterPath.scope.traverse(afterStatementsBlock, {
                    // Focus on identifiers that are read/referenced
                    Identifier(identifierPath: NodePath<t.Identifier>) {
                        // Check if it's a reference (not a declaration, not a property)
                        // and if its binding exists *outside* this temporary 'after' block
                        // (meaning it was likely declared before or is a parameter/global)
                        if (
                            identifierPath.isReferencedIdentifier() &&
                            !identifierPath.scope.hasOwnBinding(identifierPath.node.name) // Check if declared *within* the 'after' block itself
                        ) {
                            // Check if the binding exists in the *function's* scope or higher
                            const binding = path.scope.getBinding(identifierPath.node.name);
                            // We are interested in variables declared *within* the function or its parameters
                            if (binding && (binding.path.isVariableDeclarator() || binding.path.isFunctionDeclaration() || binding.path.isParameter())) {
                                usedVariableNames.add(identifierPath.node.name);
                            }
                        }
                    },
                    // Consider function declarations called after fromHere
                    CallExpression(callPath: NodePath<t.CallExpression>) {
                        if (t.isIdentifier(callPath.node.callee) && callPath.get('callee').isReferencedIdentifier()) {
                            const calleeName = callPath.node.callee.name;
                            const binding = path.scope.getBinding(calleeName);
                            // If it's bound to a function declared within this scope
                            if (binding && binding.path.isFunctionDeclaration()) {
                                usedVariableNames.add(calleeName);
                            }
                        }
                    }
                }, path.scope); // Use the function's scope as the base scope for analysis


                // --- Step 4: Identify necessary declarations BEFORE fromHere() ---
                const necessaryDeclarationNodes: t.Statement[] = [];
                const declaredBeforeNames = new Set<string>();

                beforeStatementsPaths.forEach(statementPath => {
                    // Check for Variable Declarations
                    if (statementPath.isVariableDeclaration()) {
                        statementPath.node.declarations.forEach(declarator => {
                            if (t.isIdentifier(declarator.id)) {
                                const varName = declarator.id.name;
                                declaredBeforeNames.add(varName);
                                // If this variable is used after fromHere, keep its declaration
                                if (usedVariableNames.has(varName)) {
                                    // Keep the entire VariableDeclaration statement
                                    // If multiple variables are in one declaration, we might keep unused ones too.
                                    // A more refined approach could split declarations, but adds complexity.
                                    if (!necessaryDeclarationNodes.includes(statementPath.node)) {
                                        necessaryDeclarationNodes.push(statementPath.node);
                                    }
                                }
                            }
                            // Add handling for other declaration types like ArrayPattern, ObjectPattern if needed
                        });
                    }
                    // Check for Function Declarations
                    else if (statementPath.isFunctionDeclaration()) {
                        if (statementPath.node.id) {
                            const funcName = statementPath.node.id.name;
                            declaredBeforeNames.add(funcName);
                            if (usedVariableNames.has(funcName)) {
                                necessaryDeclarationNodes.push(statementPath.node);
                            }
                        }
                    }
                    // Add checks for class declarations if necessary
                });

                // --- Step 5: Include Function Parameters if Used ---
                // Parameters are implicitly declared. Check if any are used after.
                path.get('params').forEach(paramPath => {
                    if (paramPath.isIdentifier()) {
                        if (usedVariableNames.has(paramPath.node.name)) {
                            // Parameters don't need explicit declarations kept, they exist by default.
                            // This step is mainly for awareness during analysis.
                        }
                    }
                    // Add handling for pattern parameters (destructuring) if needed
                });


                // --- Step 6: Construct the new function body ---
                const newBodyStatements: t.Statement[] = [
                    ...necessaryDeclarationNodes, // Keep necessary declarations from before
                    ...afterStatementsPaths.map(p => p.node) // Add all statements from after
                ];

                // --- Step 7: Replace the body ---
                functionBodyPath.replaceWith(t.blockStatement(newBodyStatements));

                // Optional: Re-process the scope if needed after modification
                // path.scope.crawl();
            },
        },
    };
}